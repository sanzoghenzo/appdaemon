import traceback

from jinja2 import Environment, FileSystemLoader, select_autoescape

import appdaemon.utils as utils
from appdaemon.appdaemon import AppDaemon


class Admin:
    def __init__(
        self,
        config_dir: str,
        logging,
        ad: AppDaemon,
        template_dir: str = None,
        transport: str = "ws",
        title: str = "AppDaemon Administrative Interface",
    ):
        self.config_dir = config_dir
        self.AD = ad
        self.logger = logging.get_child("_admin")
        self.template_dir = template_dir
        self.title = title
        self.transport = transport

    #
    # Methods
    #

    async def admin_page(self, scheme, url):
        try:
            params = {
                "transport": self.transport,
                "title": self.title,
                "dashboard": self.AD.http.dashboard_obj is not None,
                "logs": await self.AD.logging.get_admin_logs(),
                "namespaces": await self.AD.state.list_namespaces(),
            }
            env = Environment(
                loader=FileSystemLoader(self.template_dir),
                autoescape=select_autoescape(["html", "xml"]),
            )
            template = env.get_template("admin.jinja2")
            return await utils.run_in_executor(self, template.render, params)
        except Exception:
            self.logger.warning("-" * 60)
            self.logger.warning("Unexpected error creating admin page")
            self.logger.warning("-" * 60)
            self.logger.warning(traceback.format_exc())
            self.logger.warning("-" * 60)
