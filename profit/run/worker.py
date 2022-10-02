"""proFit worker class & components"""

import os
import shutil
import logging
from abc import abstractmethod
import time
import subprocess
from typing import Mapping, MutableMapping
from numpy import zeros, void
from warnings import warn

from ..util.component import Component
from .interface import WorkerInterface as Interface


# === Worker === #


class Worker(Component):
    def __init__(
        self,
        run_id: int,
        /,
        interface: Interface,
        debug=False,
        log_path="log",
        *,
        logger=None,
    ):
        self.run_id = run_id
        self.debug = debug

        if logger is None:
            self.logger = logging.getLogger("Worker")
            self.logger.propagate = False
            try:
                os.mkdir(log_path)
            except FileExistsError:
                pass

            log_handler = logging.FileHandler(
                os.path.join(log_path, f"run_{run_id:03d}.log"), mode="w"
            )
            if self.debug:
                log_handler.setLevel(logging.DEBUG)
            log_formatter = logging.Formatter(
                "{asctime} {levelname:8s} {name}: {message}", style="{"
            )
            log_handler.setFormatter(log_formatter)
            self.logger.addHandler(log_handler)
        else:
            self.logger = logger

        if isinstance(interface, str):
            self.interface = Interface[interface](
                self.run_id, logger_parent=self.logger
            )
        elif isinstance(interface, Mapping):
            self.interface = Interface[interface["class"]](
                self.run_id,
                **{key: value for key, value in interface.items() if key != "class"},
                logger_parent=self.logger,
            )
        else:
            self.interface = interface

    @abstractmethod
    def work(self):
        # self.interface.retrieve() -> self.interface.input
        # timestamp = time.time()
        # self.interface.output = simulate()
        # self.interface.time = int(time.time() - timestamp)
        # self.interface.transmit()
        pass

    @classmethod
    def from_env(cls, env):
        from profit.config import BaseConfig

        base_config = BaseConfig.from_file(env["PROFIT_CONFIG_PATH"])
        run_config = base_config["run"]
        run_id = int(env["PROFIT_RUN_ID"]) + int(env.get("PROFIT_ARRAY_ID", 0))

        if isinstance(worker, str):
            worker = cls[worker](run_id)
        elif isinstance(worker, Mapping):
            worker = cls[worker["class"]](
                self.run_id,
                **{key: value for key, value in worker.items() if key != "class"},
            )
        else:
            raise TypeError(f"could not create {cls} from config '{worker}'")

        return cls.from_config(run_id, run_config)

    @classmethod
    def wrap(cls, label, outputs=None, inputs=None):
        """
        ```
        @Worker.wrap('label', ['f', 'g'], ['x', 'y'])
        def func(x, y):
            ...

        @Worker.wrap('label', ['f', 'g'])
        def func(x, y):
            ...

        @Worker.wrap('label')
        def func(x, y) -> ['f', 'g']:
            ...

        @Worker.wrap('name', 'f', 'x')
        def func(x):
            ...

        @Worker.wrap('name')
        def func(x) -> 'f':
            ...

        @Worker.wrap('name')
        def f(x):
            ...
        ```
        """

        def decorator(func):
            nonlocal inputs, outputs
            if isinstance(inputs, str):
                inputs = [inputs]
            elif inputs is None:
                inputs = func.__code__.co_varnames[: func.__code__.co_argcount]
            if outputs is None:
                if "return" in func.__annotations__:
                    outputs = func.__annotations__["return"]
                else:
                    outputs = func.__code__.co_name
            if isinstance(outputs, str):
                outputs = [outputs]

            @cls.register(label)
            class WrappedWorker(cls):
                __doc__ = func.__doc__

                def work(self):
                    self.interface.retrieve()
                    self.logger.info(f"start {func.__name__}")
                    timestamp = time.time()
                    values = func(*[self.interface.input[key] for key in inputs])
                    duration = time.time() - timestamp
                    self.logger.info(
                        f"returned values: {values} after {duration:.1f} s"
                    )
                    self.interface.time = int(duration)
                    if len(outputs) == 1 and not (
                        isinstance(values, Sequence) and not isinstance(values, str)
                    ):
                        values = [values]
                    for value, key in zip(values, outputs):
                        self.interface.output[key] = value
                    self.interface.transmit()

            return WrappedWorker

        return decorator


# === Entry Point === #


def main():
    """
    entry point to run a worker

    the run id and the path to the proFit configuration is provided via environment variables
    """
    worker = Worker.from_env()
    worker.work()
    worker.clean()
