#!/usr/bin/python3

"""AppDaemon main() module.

AppDaemon module that contains main() along with argument parsing, instantiation of the AppDaemon and HTTP Objects,
also creates the loop and kicks everything off

"""
import argparse
import asyncio
import os
import os.path
import platform
import signal
import sys
from typing import Sequence, TypeVar, Any

from pydantic import ValidationError, BaseModel
import pytz

import appdaemon.appdaemon as ad
import appdaemon.http as adhttp
import appdaemon.logging as logging
import appdaemon.utils as utils
from appdaemon.config import ADConfig, HADashboardConfig, OldAdminConfig, AdminConfig, HTTPConfig

try:
    import pid
except ImportError:
    pid = None

try:
    import uvloop
except ImportError:
    uvloop = None


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-c",
        "--config",
        help="full path to config directory",
        type=str,
        default=None,
    )
    parser.add_argument("-p", "--pidfile", help="full path to PID File", default=None)
    parser.add_argument(
        "-t",
        "--timewarp",
        help="speed that the scheduler will work at for time travel",
        default=1,
        type=float,
    )
    parser.add_argument(
        "-s",
        "--starttime",
        help="start time for scheduler <YYYY-MM-DD HH:MM:SS|YYYY-MM-DD#HH:MM:SS>",
        type=str,
    )
    parser.add_argument(
        "-e",
        "--endtime",
        help="end time for scheduler <YYYY-MM-DD HH:MM:SS|YYYY-MM-DD#HH:MM:SS>",
        type=str,
        default=None,
    )
    parser.add_argument(
        "-C",
        "--configfile",
        help="name for config file",
        type=str,
        default=None,
    )
    parser.add_argument(
        "-D",
        "--debug",
        help="global debug level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    )
    parser.add_argument("-m", "--moduledebug", nargs=2, action="append")
    parser.add_argument("-v", "--version", action="version", version=f"%(prog)s {utils.__version__}")
    parser.add_argument("--profiledash", help=argparse.SUPPRESS, action="store_true")
    parser.add_argument("--toml", help="use TOML for configuration files", action="store_true")
    return parser


def _open_config_file(args, parser):
    if args.configfile is None:
        config_file = "appdaemon.toml" if args.toml is True else "appdaemon.yaml"
    else:
        config_file = args.configfile
    config_dir = args.config
    if config_dir is None:
        config_file_yaml = utils.find_path(config_file)
    else:
        config_file_yaml = os.path.join(config_dir, config_file)
    if config_file_yaml is None:
        print("FATAL: no configuration directory defined and defaults not present\n")
        parser.print_help()
        sys.exit(1)
    try:
        config = utils.read_config_file(config_file_yaml)
    except Exception as e:
        print(f"Unexpected error loading config file: {config_file_yaml}")
        print(e)
        sys.exit()
    if "appdaemon" not in config:
        print("ERROR", f"no 'appdaemon' section in {config_file_yaml}")
        sys.exit()
    return config, config_file_yaml


T = TypeVar("T", bound=BaseModel)


def _build_config(model_class: type[T], config: dict[str, Any], key: str) -> T | None:
    return model_class.model_validate(config[key] or {}) if key in config else None


def _build_ha_dashboard_config(args, config, config_file_yaml) -> HADashboardConfig:
    if "hadashboard" not in config:
        return None
    hadashboard = config["hadashboard"] or {}
    hadashboard["profile_dashboard"] = args.profiledash
    hadashboard["config_file"] = config_file_yaml
    hadashboard["config_dir"] = os.path.dirname(config_file_yaml)
    return HADashboardConfig.model_validate(hadashboard)


class ADMain:
    """
    Class to encapsulate all main() functionality.
    """

    def __init__(self):
        """Constructor."""

        self.logging = None
        self.error = None
        self.diag = None
        self.AD = None
        self.http_object = None
        self.logger = None

    def init_signals(self):
        """Setup signal handling."""

        # Windows does not support SIGUSR1 or SIGUSR2
        if platform.system() != "Windows":
            signal.signal(signal.SIGUSR1, self.handle_sig)
            signal.signal(signal.SIGINT, self.handle_sig)
            signal.signal(signal.SIGHUP, self.handle_sig)
            signal.signal(signal.SIGTERM, self.handle_sig)

    # noinspection PyUnusedLocal
    def handle_sig(self, signum, frame):
        """Function to handle signals.

        SIGUSR1 will result in internal info being dumped to the DIAG log
        SIGHUP will force a reload of all apps
        SIGINT and SIGTEM both result in AD shutting down

        Args:
            signum: Signal number being processed.
            frame: frame - unused
        """

        if signum == signal.SIGUSR1:
            self.AD.thread_async.call_async_no_wait(self.AD.sched.dump_schedule)
            self.AD.thread_async.call_async_no_wait(self.AD.callbacks.dump_callbacks)
            self.AD.thread_async.call_async_no_wait(self.AD.threading.dump_threads)
            self.AD.thread_async.call_async_no_wait(self.AD.app_management.dump_objects)
            self.AD.thread_async.call_async_no_wait(self.AD.sched.dump_sun)
        if signum == signal.SIGHUP:
            self.AD.thread_async.call_async_no_wait(self.AD.app_management.check_app_updates, mode="term")
        if signum == signal.SIGINT:
            self.logger.info("Keyboard interrupt")
            self.stop()
        if signum == signal.SIGTERM:
            self.logger.info("SIGTERM Received")
            self.stop()

    def stop(self):
        """Called by the signal handler to shut AD down."""

        self.logger.info("AppDaemon is shutting down")
        self.AD.stop()
        if self.http_object:
            self.http_object.stop()

    # noinspection PyBroadException,PyBroadException
    def run(
        self,
        appdaemon: ADConfig,
        hadashboard: HADashboardConfig,
        admin: OldAdminConfig | None,
        aui: AdminConfig | None,
        api,
        http,
    ):
        """Start AppDaemon up after initial argument parsing.

        Args:
            appdaemon: Config for AppDaemon Object.
            hadashboard: Config for HADashboard Object.
            admin: Config for admin Object.
            aui: Config for aui Object.
            api: Config for API Object
            http: Config for HTTP Object
        """

        try:
            # if to use uvloop
            if appdaemon.uvloop and uvloop:
                self.logger.info("Running AD using uvloop")
                uvloop.install()

            loop = asyncio.get_event_loop()

            self.logger.debug("Initializing AppDaemon...")
            self.AD = ad.AppDaemon(self.logging, loop, appdaemon)
            self.logger.debug("AppDaemon initialized.")

            # Initialize Dashboard/API/admin

            if http is None:
                self.logger.info("HTTP is disabled")
            elif hadashboard is None and admin is None and aui is None and api is False:
                self.logger.info("HTTP configured but no consumers are configured - disabling")
            else:
                self.logger.info("Initializing HTTP")
                self.http_object = adhttp.HTTP(
                    self.AD,
                    loop,
                    self.logging,
                    hadashboard,
                    admin,
                    aui,
                    api,
                    http,
                )
                self.AD.register_http(self.http_object)

            self.logger.debug("Start Main Loop")

            pending = asyncio.all_tasks(loop)
            loop.run_until_complete(asyncio.gather(*pending))

            #
            # Now we are shutting down - perform any necessary cleanup
            #

            self.AD.terminate()

            self.logger.info("AppDaemon is stopped.")

        except Exception:
            self.logger.warning("-" * 60)
            self.logger.warning("Unexpected error during run()")
            self.logger.warning("-" * 60, exc_info=True)
            self.logger.warning("-" * 60)

            self.logger.debug("End Loop")

            self.logger.info("AppDaemon Exited")

    # noinspection PyBroadException
    def main(self, cli_args: Sequence[str] | None = None):
        """Initial AppDaemon entry point.

        Parse command line arguments, load configuration, set up logging.
        """

        self.init_signals()
        parser = build_parser()
        args = parser.parse_args(args=cli_args)
        config, config_file_yaml = _open_config_file(args, parser)

        appdaemon = self._build_appdaemon_config(args, config_file_yaml, config["appdaemon"])

        self._setup_logging(args, config, appdaemon.get("time_zone"))
        self._startup_message(config, config_file_yaml)

        try:
            ad_config = ADConfig.model_validate(appdaemon)
        except ValidationError as e:
            self.logger.error(e)
            sys.exit(1)

        utils.check_path("config_file", self.logger, config_file_yaml, pathtype="file")

        hadashboard = _build_ha_dashboard_config(args, config, config_file_yaml)

        old_admin = _build_config(OldAdminConfig, config, "old_admin")
        admin = _build_config(AdminConfig, config, "admin")
        api = config["api"] or {} if "api" in config else None
        http = _build_config(HTTPConfig, config, "http")

        pidfile = args.pidfile
        if pidfile is None:
            self.run(ad_config, hadashboard, old_admin, admin, api, http)
        else:
            self._run_with_pidfile(ad_config, hadashboard, old_admin, admin, api, http, pidfile)

    def _setup_logging(self, args, config, time_zone):
        if "log" in config:
            print(
                "ERROR",
                "'log' directive deprecated, please convert to new 'logs' syntax",
            )
            sys.exit(1)
        logs = config.get("logs", {})
        self.logging = logging.Logging(logs, args.debug)
        self.logger = self.logging.get_logger()
        if time_zone:
            self.logging.set_tz(pytz.timezone(time_zone))

    def _build_appdaemon_config(self, args, config_file_yaml, appdaemon):
        appdaemon["use_toml"] = args.toml
        appdaemon["config_file"] = config_file_yaml
        appdaemon["app_config_file"] = os.path.join(os.path.dirname(config_file_yaml), "apps.yaml")
        appdaemon["module_debug"] = dict(args.moduledebug or {})
        if args.starttime is not None:
            appdaemon["starttime"] = args.starttime
        if args.endtime is not None:
            appdaemon["endtime"] = args.endtime
        if "timewarp" not in appdaemon:
            appdaemon["timewarp"] = args.timewarp
        appdaemon["loglevel"] = args.debug
        appdaemon["config_dir"] = os.path.dirname(config_file_yaml)
        appdaemon["stop_function"] = self.stop
        return appdaemon

    def _run_with_pidfile(self, ad_config, had_config, old_admin, admin, api, http, pidfile):
        self.logger.info("Using pidfile: %s", pidfile)
        pid_dir = os.path.dirname(pidfile)
        name = os.path.basename(pidfile)
        try:
            with pid.PidFile(name, pid_dir):
                self.run(ad_config, had_config, old_admin, admin, api, http)
        except pid.PidFileError:
            self.logger.error("Unable to acquire pidfile - terminating")

    def _startup_message(self, config, config_file_yaml):
        self.logger.info("AppDaemon Version %s starting", utils.__version__)
        self.logger.info(
            "Python version is %s.%s.%s",
            sys.version_info[0],
            sys.version_info[1],
            sys.version_info[2],
        )
        self.logger.info("Configuration read from: %s", config_file_yaml)
        self.logging.dump_log_config()
        self.logger.debug("AppDaemon Section: %s", config.get("appdaemon"))
        self.logger.debug("HADashboard Section: %s", config.get("hadashboard"))


def main():
    """Called when run from the command line."""
    admain = ADMain()
    admain.main()


if __name__ == "__main__":
    main()
