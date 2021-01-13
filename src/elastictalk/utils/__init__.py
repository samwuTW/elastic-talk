import re
import copy
import datetime
import typing
import pathlib
import contextlib
from distutils import util as distutils_util
from ebcli.lib import elasticbeanstalk
from ebcli.controllers import create as create_controller
from ebcli.objects import requests as eb_requests
from ebcli.operations import cloneops


DB_URL_PATTERN = \
    r'(?P<connection_info>.*)@(?P<address>.*):(?P<port_slash_db>.*)'


def set_last_id_to_file(file_name: str, id_: str) -> None:
    with open(file_name, 'a') as f:
        f.write(id_)
        f.write('\n')


def get_last_id_from_file(file_name: str) -> str:
    id_ = None
    if not pathlib.Path(file_name).exists():
        return id_
    with open(file_name) as f:
        lines = f.read().splitlines()
        if lines:
            id_ = lines[-1]
    return id_


def eb_clone(
        app_name: str,
        env_name: str,
        clone_name: str,
        env_var: dict,
        scale: int = 1,
        platform: str = None,
        tags: list = None,
        nohang: bool = False,
        timeout: int = 30,
):
    env_var = get_eb_env_from_dict(env_var)
    cname = create_controller.get_cname_from_customer(clone_name)
    tags = tags or []
    clone_request = eb_requests.CloneEnvironmentRequest(
        app_name=app_name,
        env_name=clone_name,
        original_name=env_name,
        cname=cname,
        platform=platform,
        scale=scale,
        tags=tags,
    )
    clone_request.option_settings += env_var
    cloneops.make_cloned_env(
        clone_request,
        nohang=nohang,
        timeout=timeout
    )


def now_string(datetime_format: str = None):
    datetime_format = datetime_format or '%Y-%m-%d-%H-%M-%S'
    return datetime.datetime.now().strftime(datetime_format)


def get_env(app_name, env_name):
    namespace = 'aws:elasticbeanstalk:application:environment'
    configuration_settings = elasticbeanstalk.describe_configuration_settings(
        app_name,
        env_name,
    )
    settings = configuration_settings['OptionSettings']
    environment_variables = {
        setting['OptionName']: setting['Value']
        for setting in settings
        if setting["Namespace"] == namespace
    }
    return environment_variables


def get_eb_env_from_dict(
        env_var: dict,
) -> typing.List[typing.Dict[str, str]]:
    namespace = 'aws:elasticbeanstalk:application:environment'
    env_var_list = list()
    for environment_variable, value in env_var.items():
        env_var_list.append(
            dict(
                Namespace=namespace,
                OptionName=environment_variable,
                Value=value
            )
        )
    return env_var_list


def get_input_boolean(message):
    while True:
        with contextlib.suppress(Exception):
            input_bool = distutils_util.strtobool(input(
                message
            ))
            return input_bool


def update_env_cache_like(
        env_var: dict,
        cache_endpoint: dict
) -> dict:
    env_var = copy.deepcopy(env_var)
    cache_addr, cache_port = cache_endpoint['Address'], cache_endpoint['Port']
    for key, val in env_var.items():
        if 'cache.amazonaws.com' in val:
            new_val = []
            for link in env_var[key].split(','):
                new_link = f'{cache_addr}:{cache_port}' if ':' in link else cache_addr
                change = get_input_boolean(
                    f'Change {key}: {link} address to {new_link} (y/n)'
                )
                if change:
                    new_val.append(new_link)
                else:
                    remove = get_input_boolean(
                        f'Remove {key}: {link} address (y/n)'
                    )
                    if not remove:
                        new_val.append(link)
            env_var[key] = ','.join(new_val)
    return env_var


def update_env_db_url(
        env_var: dict,
        endpoint_addr: str,
) -> dict:
    env_var = copy.deepcopy(env_var)
    db_like_keys = list(filter(
        lambda key: 'DATABASE_URL' in key,
        env_var.keys()
    ))
    for db_like_key in db_like_keys:
        database_url = env_var[db_like_key]
        change = get_input_boolean(
            f'Change {db_like_key}: {database_url} address to '
            f'{endpoint_addr} (y/n)'
        )
        if change:
            db_info = re.match(
                DB_URL_PATTERN,
                database_url
            ).groupdict()
            env_var[db_like_key] = (
                f'{db_info["connection_info"]}'
                f'@{endpoint_addr}'
                f':{db_info["port_slash_db"]}'
            )
            print(f'Changed {db_like_key} to {env_var[db_like_key]}')
    return env_var
