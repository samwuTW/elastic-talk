import logging
import typing


logger = logging.getLogger(__name__)


class NotCallableError(Exception):
    pass


class Pipe:
    '''
    Failure free job pipe line, it run jobs and not raise error by default but
    break next jobs on failure.
    '''

    def __init__(
            self,
            jobs: typing.List[typing.Callable],
            on_failure: typing.Callable = None,
    ):
        """
        Give jobs to run, give on_failure(job: typing.Callable, error: Exception)
        to handle error on running job failure
        """
        self.jobs = jobs
        self.on_failure = on_failure

    def handle_failure(
            self,
            job: typing.Callable,
            error: Exception
    ):
        if callable(self.on_failure):
            self.on_failure(job, error)
        else:
            logger.error(
                'Run jobs '
                f'{[job for job in self.jobs]} failed on {job} got {error}'
            )
            logger.exception(error)

    def start(self):
        for job in self.jobs:
            if callable(job):
                try:
                    job()
                except Exception as error:
                    self.handle_failure(job, error)
                    return
            else:
                error = NotCallableError(f'Job {job} is not callable')
                self.handle_failure(job, error)
                return
