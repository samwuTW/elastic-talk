import json
import fire
import yaml
import boto3
import pathlib
import functools
from ebcli.lib import elasticbeanstalk
from ebcli.operations import commonops
from elastictalk import utils, pipe


eb = boto3.client('elasticbeanstalk')
eb_terminated_waiter = eb.get_waiter('environment_terminated')
rds = boto3.client('rds')
rds_available_waiter = rds.get_waiter('db_instance_available')
rds_deleted_waiter = rds.get_waiter('db_instance_deleted')
rds_snapshot_waiter = rds.get_waiter('db_snapshot_completed')
elasticache = boto3.client('elasticache')
elasticache_available_waiter = elasticache.get_waiter('cache_cluster_available')
elasticache_deleted_waiter = elasticache.get_waiter('cache_cluster_deleted')


class ElasticTalk:
    last_rds_log_file_name = 'last_rds_id.txt'
    last_rds_snapshot_log_file_name = 'last_rds_snapshot_id.txt'
    last_elasticache_log_file_name = 'last_cache_id.txt'

    def __init__(
            self,
            app_name=None,
            env_name=None,
            config_file='.elasticbeanstalk/config.yml'
    ):
        self.config_file = None
        if pathlib.Path(config_file).exists():
            self.config_file = config_file
        self.app_name = app_name
        self.env_name = env_name
        if self.config_file:
            with pathlib.Path(config_file).open() as config:
                self.config_data = yaml.load(config, Loader=yaml.FullLoader)
            if 'global' in self.config_data and \
               'application_name' in self.config_data['global']:
                self.app_name = self.app_name or \
                    self.config_data['global']['application_name']
            '''
            'branch-defaults': {'default': {'environment': 'Ponddy-Auth-develop'}}
            '''
            if 'branch-defaults' in self.config_data and \
               'default' in self.config_data['branch-defaults'] and \
               'environment' in self.config_data['branch-defaults']['default']:
                self.env_name = self.env_name or \
                    self.config_data['branch-defaults']['default']['environment']
        if not any([
                all([self.app_name, self.env_name]),
                self.config_file,
        ]):
            raise Exception(
                'Please give config.yml file path or app_name and env_name'
            )
        print(f'Use app_name={self.app_name}, env_name={self.env_name}')

    def save_env_var(self, env_file=None):
        env_file = env_file or f'{self.env_name}.env.json'
        env_var = utils.get_env(self.app_name, self.env_name)
        with pathlib.Path(env_file).open('w') as saved_file:
            json.dump(env_var, saved_file)
        print(
            f'Saved {self.app_name}:{self.env_name}'
            f' environment variables to {env_file}'
        )

    def get_env_var_from_file(self, env_file: str = None):
        env_file = env_file or f'{self.env_name}.env.json'
        if not pathlib.Path(env_file).exists():
            raise(f'Cannot open file {env_file}, the env_file not found')
        with pathlib.Path(env_file).open() as saved_file:
            env_var = json.load(saved_file)
        print(f'Loaded data from {env_file}')
        return env_var

    def update_eb_env(self, env_var, timeout=None):
        # Follow ebcli.operations.envvarops.setenv
        # Follow ebcli.operations.envvarops.create_environment_variables_list
        env_var_list = utils.get_eb_env_from_dict(env_var)
        request_id = elasticbeanstalk.update_environment(
            self.env_name,
            env_var_list,
        )
        if timeout is None:
            timeout = 30
        commonops.wait_for_success_events(
            request_id,
            timeout_in_minutes=timeout,
            can_abort=True
        )
        print('Updated environment variables')

    def update_env_var_by_file(self, env_file, timeout=None):
        env_var = self.get_env_var_from_file(env_file)
        self.update_eb_env(env_var)

    def create_elasticache(
            self,
            cache_id,
            node_type='cache.t3.micro',
            engine='redis',
            num_of_nodes=1,
            waiting=True,
            elasticache_log_file_name=None,
    ):
        elasticache_log_file_name = elasticache_log_file_name or \
            self.last_elasticache_log_file_name
        print(f'Creating ElastiCache: {cache_id}')
        response = elasticache.create_cache_cluster(
            CacheClusterId=cache_id,
            CacheNodeType=node_type,
            Engine=engine,
            NumCacheNodes=num_of_nodes,
        )
        print(response)
        if waiting:
            print(f'Waiting for creating ElastiCache {cache_id}')
            elasticache_available_waiter.wait(CacheClusterId=cache_id)
        print(
            'Create ElastiCach successfully',
            f'{"with" if waiting else "without"} waiting',
        )
        utils.set_last_id_to_file(
            elasticache_log_file_name,
            cache_id,
        )
        return cache_id

    def build_staging_pipe(
            self,
            clone_from_env_name,
            rds_id=None,
            env_file=None,
            clone_name=None,
            cache_id=None,
            rds_snapshot_id=None,
            rds_snapshot_log_file=None,
            rds_log_file_name=None,
            elasticache_log_file_name=None,
    ):
        # Get env variable from saved
        env_var = self.get_env_var_from_file(env_file)
        # Create RDS from snapshot
        rds_id = rds_id or self.get_last_rds_id(rds_log_file_name)
        rds_snapshot_id = rds_snapshot_id or self.get_last_snapshot_id(
            rds_snapshot_log_file
        )
        cache_id = cache_id or self.get_last_cache_id(elasticache_log_file_name)

        if rds_id:
            jobs = list()
            if rds_snapshot_id:
                restore_db_from_snapshot = functools.partial(
                    self.restore_db_from_snapshot,
                    rds_id=rds_id,
                    rds_snapshot_id=rds_snapshot_id,
                )
                jobs.append(restore_db_from_snapshot)

            def update_env_db_url():
                nonlocal env_var
                rds_detail = rds.describe_db_instances(DBInstanceIdentifier=rds_id)
                endpoint_addr = rds_detail['DBInstances'][-1]['Endpoint']['Address']
                print(f'Staging RDS endpoint is : {endpoint_addr}')

                # Update env variable from created RDS
                if endpoint_addr:
                    env_var = utils.update_env_db_url(env_var, endpoint_addr)

            jobs.append(update_env_db_url)
            pipe.Pipe(jobs=jobs).start()

        # Create elastic Cache
        if cache_id:
            jobs = list()
            jobs.append(functools.partial(
                self.create_elasticache,
                cache_id,
            ))
            # Update env variable from created elastiCache

            def update_env_cache():
                nonlocal env_var
                cache_detail = elasticache.describe_cache_clusters(
                    ShowCacheNodeInfo=True,
                    CacheClusterId=cache_id,
                )
                cache_endpoint = \
                    cache_detail['CacheClusters'][0]['CacheNodes'][0]['Endpoint']
                env_var = utils.update_env_cache_like(
                    env_var,
                    cache_endpoint,
                )

            jobs.append(update_env_cache)
            pipe.Pipe(jobs=jobs).start()
        # Clone from master with eb env variables
        clone_name = clone_name or '-'.join(
            self.env_name.split('-')[:-1] + ['staging']
        )
        utils.eb_clone(
            self.app_name,
            clone_from_env_name,
            self.env_name,
            env_var,
        )
        return clone_name

    def get_last_cache_id(self, elasticache_log_file_name: str = None) -> str:
        elasticache_log_file_name = elasticache_log_file_name or \
            self.last_elasticache_log_file_name
        return utils.get_last_id_from_file(elasticache_log_file_name)

    def get_last_rds_id(self, rds_log_file_name: str = None) -> str:
        rds_log_file_name = rds_log_file_name or \
            self.last_rds_log_file_name
        return utils.get_last_id_from_file(rds_log_file_name)

    def get_last_snapshot_id(self, rds_snapshot_log_file_name: str = None) -> str:
        rds_snapshot_log_file_name = rds_snapshot_log_file_name or \
            self.last_rds_snapshot_log_file_name
        return utils.get_last_id_from_file(rds_snapshot_log_file_name)

    def restore_db_from_snapshot(
            self,
            rds_id=None,
            rds_snapshot_id=None,
            rds_snapshot_log_file=None,
            rds_instance_class='db.t3.micro',
            rds_engine='postgres',
            publicly_accessible=True,
            multi_az=False,
            waiting=True,
            rds_log_file_name=None,
    ):
        rds_log_file_name = rds_log_file_name or self.last_rds_log_file_name
        rds_id = rds_id or self.get_last_rds_id(rds_log_file_name)
        if not rds_snapshot_id:
            rds_snapshot_id = self.get_last_snapshot_id(rds_snapshot_log_file)
        if not rds_snapshot_id:
            raise Exception('Please give the snapshot_id')
        if not rds_id:
            raise Exception('Please give the rds_id')
        print(f'Restoring RDS: {rds_snapshot_id} as {rds_id}')
        response = rds.restore_db_instance_from_db_snapshot(
            DBInstanceIdentifier=rds_id,
            DBSnapshotIdentifier=rds_snapshot_id,
            DBInstanceClass=rds_instance_class,
            PubliclyAccessible=publicly_accessible,
            MultiAZ=multi_az,
            Tags=[
                {
                    'Key': 'From',
                    'Value': f'Auto create by sanpshot {rds_snapshot_id}'
                },
            ]
        )
        print(response)
        if waiting:
            print(f'Waiting for restoring snapshot {rds_snapshot_id} as {rds_id}')
            rds_available_waiter.wait(DBInstanceIdentifier=rds_id)
        print(
            'Restore RDS Snapshot successfully',
            f'DBSnapshotIdentifier={rds_snapshot_id}',
            f'DBInstanceIdentifier={rds_id}',
            f'{"with" if waiting else "without"} waiting',
        )
        utils.set_last_id_to_file(
            rds_log_file_name,
            rds_id,
        )
        return rds_id

    def take_rds_snapshot(
            self,
            rds_id,
            rds_snapshot_id=None,
            rds_snapshot_log_file=None,
            waiting=True,
    ) -> str:
        rds_snapshot_log_file = rds_snapshot_log_file or \
            self.last_rds_snapshot_log_file_name
        rds_snapshot_id = rds_snapshot_id or \
            (f'{self.app_name.replace(" ", "-")}-'
             f'{self.env_name.replace(" ", "-")}-'
             f'{utils.now_string()}').lower()
        response = rds.create_db_snapshot(
            DBInstanceIdentifier=rds_id,
            DBSnapshotIdentifier=rds_snapshot_id,
        )
        print(response)
        if waiting:
            print('Waiting for taking snapshot')
            rds_snapshot_waiter.wait(
                DBInstanceIdentifier=rds_id,
                DBSnapshotIdentifier=rds_snapshot_id,
            )
        print(
            'Create RDS Snapshot successfully',
            f'DBSnapshotIdentifier={rds_snapshot_id}',
            f'DBInstanceIdentifier={rds_id}',
            f'{"with" if waiting else "without"} waiting',
        )
        utils.set_last_id_to_file(
            rds_snapshot_log_file,
            rds_snapshot_id,
        )
        return rds_snapshot_id

    def remove_staging_pipe(
            self,
            rds_id=None,
            rds_snapshot_id=None,
            cache_id=None,
            waiting=True,
            rds_log_file_name=None,
            elasticache_log_file_name=None,
    ):
        rds_log_file_name = rds_log_file_name or self.last_rds_log_file_name
        rds_id = rds_id or self.get_last_rds_id(rds_log_file_name)
        elasticache_log_file_name = elasticache_log_file_name or \
            self.last_elasticache_log_file_name
        cache_id = cache_id or self.get_last_cache_id(elasticache_log_file_name)

        jobs = list()
        # Save eb env variables
        jobs.append(self.save_env_var)
        # Remove eb
        jobs.append(
            functools.partial(
                eb.terminate_environment,
                EnvironmentName=self.env_name,
            )
        )
        if waiting:
            jobs.append(
                functools.partial(
                    print,
                    f'Waiting for terminating EB environment {self.env_name}'
                )
            )
            jobs.append(
                functools.partial(
                    eb_terminated_waiter.wait,
                    ApplicationName=self.app_name,
                    EnvironmentNames=[
                        self.env_name,
                    ],
                    WaiterConfig={
                        'Delay': 60,
                        'MaxAttempts': 100,
                    }
                )
            )
        jobs.append(
            functools.partial(
                print,
                (
                    f'Terminated EB environment {self.env_name} successfully',
                    f'{"with" if waiting else "without"} waiting',
                )
            )
        )
        pipe.Pipe(jobs=jobs).start()

        if rds_id:
            jobs = list()
            # Save RDS to snapshot
            take_rds_snapshot = functools.partial(
                self.take_rds_snapshot,
                rds_id,
                rds_snapshot_id=rds_snapshot_id,
                waiting=waiting,
            )
            jobs.append(take_rds_snapshot)
            delete_db_instance = functools.partial(
                rds.delete_db_instance,
                DBInstanceIdentifier=rds_id,
                SkipFinalSnapshot=True,
            )
            jobs.append(delete_db_instance)
            if waiting:
                jobs.append(
                    functools.partial(print, f'Waiting for deleting RDS {rds_id}')
                )
                jobs.append(
                    functools.partial(
                        rds_deleted_waiter.wait,
                        DBInstanceIdentifier=rds_id,
                    )
                )
            jobs.append(functools.partial(
                print,
                (
                    f'Deleted RDS {rds_id} successfully',
                    f'{"with" if waiting else "without"} waiting',
                )
            ))
            jobs.append(functools.partial(
                utils.set_last_id_to_file,
                rds_log_file_name,
                rds_id,
            ))
            pipe.Pipe(jobs=jobs).start()

        # Remove elastiCache
        if cache_id:
            jobs = list()
            jobs.append(
                functools.partial(
                    elasticache.delete_cache_cluster,
                    CacheClusterId=cache_id,
                    FinalSnapshotIdentifier=f'{cache_id}-{utils.now_string()}',
                )
            )
            if waiting:
                jobs.append(
                    functools.partial(
                        print,
                        f'Waiting for deleting ElastiCache {cache_id}'
                    )
                )
                jobs.append(
                    functools.partial(
                        elasticache_deleted_waiter.wait,
                        CacheClusterId=cache_id,
                    )
                )
            jobs.append(
                functools.partial(
                    print,
                    (
                        f'Deleted ElastiCache {cache_id} successfully',
                        f'{"with" if waiting else "without"} waiting',
                    )
                )
            )
            jobs.append(
                functools.partial(
                    utils.set_last_id_to_file,
                    elasticache_log_file_name,
                    cache_id,
                )
            )
            pipe.Pipe(jobs=jobs).start()

        print('Completed remove staging')


def main():
    fire.Fire(ElasticTalk)


if __name__ == '__main__':
    main()
