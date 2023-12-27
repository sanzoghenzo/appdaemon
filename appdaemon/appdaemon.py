import concurrent.futures
import os
import os.path
import threading

from appdaemon.config import ADConfig


class AppDaemon:
    def __init__(self, logging, loop, ad_config: ADConfig, **kwargs):
        #
        # Import various AppDaemon bits and pieces now to avoid circular import
        #

        import appdaemon.app_management as apps
        import appdaemon.callbacks as callbacks
        import appdaemon.events as events
        import appdaemon.futures as futures
        import appdaemon.plugin_management as plugins
        import appdaemon.scheduler as scheduler
        import appdaemon.sequences as sequences
        import appdaemon.services as services
        import appdaemon.state as state
        import appdaemon.thread_async as appq
        import appdaemon.threading
        import appdaemon.utility_loop as utility
        import appdaemon.utils as utils

        self.logging = logging
        self.logger = logging.get_logger()
        self.config = ad_config

        logging.set_tz(self.config.tz)

        # TODO: resolve coupling of logging and these
        self.callbacks = None
        self.events = None
        self.thread_async = None
        self.logging.register_ad(self)

        self.booted = "booting"
        self.stopping = False

        self.http = None
        self.admin_loop = None

        self.global_vars = {}
        self.global_lock = threading.RLock()

        self.utility = None

        if not self.config.apps:
            self.logging.log("INFO", "Apps are disabled")

        self.loop = loop

        # Set up services
        #
        self.services = services.Services(self)

        #
        # Set up sequences
        #
        self.sequences = sequences.Sequences(self)

        #
        # Set up scheduler
        #
        self.sched = scheduler.Scheduler(self)

        #
        # Set up state
        #
        self.state = state.State(self)

        #
        # Set up events
        #
        self.events = events.Events(self)

        #
        # Set up callbacks
        #
        self.callbacks = callbacks.Callbacks(self)

        #
        # Set up futures
        #
        self.futures = futures.Futures(self)

        self.threading = None
        if self.apps:
            if self.app_dir is None:
                if self.config_dir is None:
                    self.app_dir = utils.find_path("apps")
                    self.config_dir = os.path.dirname(self.app_dir)
                else:
                    self.app_dir = os.path.join(self.config_dir, "apps")

            utils.check_path("config_dir", self.logger, self.config_dir, permissions="rwx")
            utils.check_path("appdir", self.logger, self.app_dir)

            # Initialize Apps

            self.app_management = apps.AppManagement(self, self.use_toml)

            # threading setup

            self.threading = appdaemon.threading.Threading(self, kwargs)

        self.stopping = False

        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=self.threadpool_workers)

        # Initialize Plugins
        self.plugins = plugins.Plugins(self, kwargs.get("plugins", {}))

        # Create thread_async Loop

        self.logger.debug("Starting thread_async loop")
        self.thread_async = None
        if self.apps:
            self.thread_async = appq.ThreadAsync(self)
            loop.create_task(self.thread_async.loop())

        # Create utility loop

        self.logger.debug("Starting utility loop")

        self.utility = utility.Utility(self)
        loop.create_task(self.utility.loop())

    def __getattr__(self, item):
        # HACK to maintain backwards compatibility
        return getattr(self.config, item)

    def stop(self):
        self.stopping = True
        if self.admin_loop is not None:
            self.admin_loop.stop()
        if self.thread_async is not None:
            self.thread_async.stop()
        if self.sched is not None:
            self.sched.stop()
        if self.utility is not None:
            self.utility.stop()
        if self.plugins is not None:
            self.plugins.stop()

    def terminate(self):
        if self.state is not None:
            self.state.terminate()

    #
    # Utilities
    #

    def register_http(self, http):
        import appdaemon.admin_loop as admin_loop

        self.http = http
        # Create admin loop

        if http.old_admin is not None or http.admin is not None:
            self.logger.debug("Starting admin loop")

            self.admin_loop = admin_loop.AdminLoop(self)
            self.loop.create_task(self.admin_loop.loop())
