import json

from configs import dify_config
from extensions.ext_database import db
from models.model import App, AppMode, AppModelConfig
from models.tools import PublicToolProvider
from services.app_service import AppService


class CustomService(AppService):
    def get_app_meta(self, app_model: App) -> dict:
        """
        Get app meta info
        :param app_model: app model
        :return:
        """
        app_mode = AppMode.value_of(app_model.mode)

        meta = {"tool_icons": {}}

        if app_mode in {AppMode.ADVANCED_CHAT, AppMode.WORKFLOW}:
            workflow = app_model.workflow
            if workflow is None:
                return meta

            graph = workflow.graph_dict
            nodes = graph.get("nodes", [])
            tools = []
            for node in nodes:
                if node.get("data", {}).get("type") == "tool":
                    node_data = node.get("data", {})
                    tools.append(
                        {
                            "provider_type": node_data.get("provider_type"),
                            "provider_id": node_data.get("provider_id"),
                            "tool_name": node_data.get("tool_name"),
                            "tool_parameters": {},
                        }
                    )
        else:
            app_model_config: AppModelConfig = app_model.app_model_config

            if not app_model_config:
                return meta

            agent_config = app_model_config.agent_mode_dict or {}

            # get all tools
            tools = agent_config.get("tools", [])

        url_prefix = dify_config.CONSOLE_API_URL + "/console/api/workspaces/current/tool-provider/builtin/"

        for tool in tools:
            keys = list(tool.keys())
            if len(keys) >= 4:
                # current tool standard
                provider_type = tool.get("provider_type")
                provider_id = tool.get("provider_id")
                tool_name = tool.get("tool_name")
                if provider_type == "builtin":
                    meta["tool_icons"][tool_name] = url_prefix + provider_id + "/icon"
                elif provider_type == "api":
                    try:
                        provider: PublicToolProvider = (
                            db.session.query(PublicToolProvider).filter(PublicToolProvider.id == provider_id).first()
                        )
                        meta["tool_icons"][tool_name] = json.loads(provider.icon)
                    except:
                        meta["tool_icons"][tool_name] = {"background": "#252525", "content": "\ud83d\ude01"}

        return meta
