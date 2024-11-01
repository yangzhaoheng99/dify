import json
import logging

from core.model_runtime.utils.encoders import jsonable_encoder
from core.tools.entities.api_entities import UserTool, UserToolProvider
from core.tools.entities.tool_entities import (
    ApiProviderAuthType,
    ApiProviderSchemaType,
)
from core.tools.provider.api_tool_provider import ApiToolProviderController
from core.tools.tool_label_manager import ToolLabelManager
from core.tools.tool_manager import ToolManager
from core.tools.utils.configuration import ToolConfigurationManager
from core.tools.utils.parser import ApiBasedToolSchemaParser
from extensions.ext_database import db
from models.tools import PublicToolProvider
from services.tools.api_tools_manage_service import ApiToolManageService
from services.tools.tools_transform_service import ToolTransformService

logger = logging.getLogger(__name__)


class PublicToolManageService(ApiToolManageService):
    @staticmethod
    def create_api_tool_provider(
        user_id: str,
        tenant_id: str,
        provider_name: str,
        icon: dict,
        credentials: dict,
        schema_type: str,
        schema: str,
        privacy_policy: str,
        custom_disclaimer: str,
        labels: list[str],
    ):
        """
        create public tool provider
        """
        if schema_type not in [member.value for member in ApiProviderSchemaType]:
            raise ValueError(f"invalid schema type {schema}")

        # check if the provider exists
        provider: PublicToolProvider = (
            db.session.query(PublicToolProvider)
            .filter(
                PublicToolProvider.tenant_id == tenant_id,
                PublicToolProvider.name == provider_name,
            )
            .first()
        )

        if provider is not None:
            raise ValueError(f"provider {provider_name} already exists")

        # parse openapi to tool bundle
        extra_info = {}
        # extra info like description will be set here
        tool_bundles, schema_type = PublicToolManageService.convert_schema_to_tool_bundles(schema, extra_info)

        if len(tool_bundles) > 100:
            raise ValueError("the number of apis should be less than 100")

        # create db provider
        db_provider = PublicToolProvider(
            tenant_id=tenant_id,
            user_id=user_id,
            name=provider_name,
            icon=json.dumps(icon),
            schema=schema,
            description=extra_info.get("description", ""),
            schema_type_str=schema_type,
            tools_str=json.dumps(jsonable_encoder(tool_bundles)),
            credentials_str={},
            privacy_policy=privacy_policy,
            custom_disclaimer=custom_disclaimer,
        )

        if "auth_type" not in credentials:
            raise ValueError("auth_type is required")

        # get auth type, none or api key
        auth_type = ApiProviderAuthType.value_of(credentials["auth_type"])

        # create provider entity
        provider_controller = ApiToolProviderController.from_db(db_provider, auth_type)
        # load tools into provider entity
        provider_controller.load_bundled_tools(tool_bundles)

        # encrypt credentials
        tool_configuration = ToolConfigurationManager(tenant_id=tenant_id, provider_controller=provider_controller)
        encrypted_credentials = tool_configuration.encrypt_tool_credentials(credentials)
        db_provider.credentials_str = json.dumps(encrypted_credentials)

        db.session.add(db_provider)
        db.session.commit()

        # update labels
        ToolLabelManager.update_tool_labels(provider_controller, labels)

        return {"result": "success"}

    @staticmethod
    def list_api_tool_provider_tools(user_id: str, tenant_id: str, provider: str) -> list[UserTool]:
        """
        list api tool provider tools
        """
        provider: PublicToolProvider = (
            db.session.query(PublicToolProvider)
            .filter(
                PublicToolProvider.tenant_id == tenant_id,
                PublicToolProvider.name == provider,
            )
            .first()
        )

        if provider is None:
            raise ValueError(f"you have not added provider {provider}")

        controller = ToolTransformService.api_provider_to_controller(db_provider=provider)
        labels = ToolLabelManager.get_tool_labels(controller)

        return [
            ToolTransformService.tool_to_user_tool(
                tool_bundle,
                labels=labels,
            )
            for tool_bundle in provider.tools
        ]

    @staticmethod
    def update_api_tool_provider(
        user_id: str,
        tenant_id: str,
        provider_name: str,
        original_provider: str,
        icon: dict,
        credentials: dict,
        schema_type: str,
        schema: str,
        privacy_policy: str,
        custom_disclaimer: str,
        labels: list[str],
    ):
        """
        update api tool provider
        """
        if schema_type not in [member.value for member in ApiProviderSchemaType]:
            raise ValueError(f"invalid schema type {schema}")

        # check if the provider exists
        provider: PublicToolProvider = (
            db.session.query(PublicToolProvider)
            .filter(
                PublicToolProvider.tenant_id == tenant_id,
                PublicToolProvider.name == original_provider,
            )
            .first()
        )

        if provider is None:
            raise ValueError(f"api provider {provider_name} does not exists")

        # parse openapi to tool bundle
        extra_info = {}
        # extra info like description will be set here
        tool_bundles, schema_type = ApiToolManageService.convert_schema_to_tool_bundles(schema, extra_info)

        # update db provider
        provider.name = provider_name
        provider.icon = json.dumps(icon)
        provider.schema = schema
        provider.description = extra_info.get("description", "")
        provider.schema_type_str = ApiProviderSchemaType.OPENAPI.value
        provider.tools_str = json.dumps(jsonable_encoder(tool_bundles))
        provider.privacy_policy = privacy_policy
        provider.custom_disclaimer = custom_disclaimer

        if "auth_type" not in credentials:
            raise ValueError("auth_type is required")

        # get auth type, none or api key
        auth_type = ApiProviderAuthType.value_of(credentials["auth_type"])

        # create provider entity
        provider_controller = ApiToolProviderController.from_db(provider, auth_type)
        # load tools into provider entity
        provider_controller.load_bundled_tools(tool_bundles)

        # get original credentials if exists
        tool_configuration = ToolConfigurationManager(tenant_id=tenant_id, provider_controller=provider_controller)

        original_credentials = tool_configuration.decrypt_tool_credentials(provider.credentials)
        masked_credentials = tool_configuration.mask_tool_credentials(original_credentials)
        # check if the credential has changed, save the original credential
        for name, value in credentials.items():
            if name in masked_credentials and value == masked_credentials[name]:
                credentials[name] = original_credentials[name]

        credentials = tool_configuration.encrypt_tool_credentials(credentials)
        provider.credentials_str = json.dumps(credentials)

        db.session.add(provider)
        db.session.commit()

        # delete cache
        tool_configuration.delete_tool_credentials_cache()

        # update labels
        ToolLabelManager.update_tool_labels(provider_controller, labels)

        return {"result": "success"}

    @staticmethod
    def delete_api_tool_provider(user_id: str, tenant_id: str, provider_name: str):
        """
        delete tool provider
        """
        provider: PublicToolProvider = (
            db.session.query(PublicToolProvider)
            .filter(
                PublicToolProvider.tenant_id == tenant_id,
                PublicToolProvider.name == provider_name,
            )
            .first()
        )

        if provider is None:
            raise ValueError(f"you have not added provider {provider_name}")

        db.session.delete(provider)
        db.session.commit()

        return {"result": "success"}

    @staticmethod
    def get_api_tool_provider(user_id: str, tenant_id: str, provider: str):
        """
        get api tool provider
        """
        return ToolManager.user_get_public_provider(provider=provider, tenant_id=tenant_id)

    @staticmethod
    def test_api_tool_preview(
        tenant_id: str,
        provider_name: str,
        tool_name: str,
        credentials: dict,
        parameters: dict,
        schema_type: str,
        schema: str,
    ):
        """
        test api tool before adding api tool provider
        """
        if schema_type not in [member.value for member in ApiProviderSchemaType]:
            raise ValueError(f"invalid schema type {schema_type}")

        try:
            tool_bundles, _ = ApiBasedToolSchemaParser.auto_parse_to_tool_bundle(schema)
        except Exception as e:
            raise ValueError("invalid schema")

        # get tool bundle
        tool_bundle = next(filter(lambda tb: tb.operation_id == tool_name, tool_bundles), None)
        if tool_bundle is None:
            raise ValueError(f"invalid tool name {tool_name}")

        db_provider: PublicToolProvider = (
            db.session.query(PublicToolProvider)
            .filter(
                PublicToolProvider.tenant_id == tenant_id,
                PublicToolProvider.name == provider_name,
            )
            .first()
        )

        if not db_provider:
            # create a fake db provider
            db_provider = PublicToolProvider(
                tenant_id="",
                user_id="",
                name="",
                icon="",
                schema=schema,
                description="",
                schema_type_str=ApiProviderSchemaType.OPENAPI.value,
                tools_str=json.dumps(jsonable_encoder(tool_bundles)),
                credentials_str=json.dumps(credentials),
            )

        if "auth_type" not in credentials:
            raise ValueError("auth_type is required")

        # get auth type, none or api key
        auth_type = ApiProviderAuthType.value_of(credentials["auth_type"])

        # create provider entity
        provider_controller = ApiToolProviderController.from_db(db_provider, auth_type)
        # load tools into provider entity
        provider_controller.load_bundled_tools(tool_bundles)

        # decrypt credentials
        if db_provider.id:
            tool_configuration = ToolConfigurationManager(tenant_id=tenant_id, provider_controller=provider_controller)
            decrypted_credentials = tool_configuration.decrypt_tool_credentials(credentials)
            # check if the credential has changed, save the original credential
            masked_credentials = tool_configuration.mask_tool_credentials(decrypted_credentials)
            for name, value in credentials.items():
                if name in masked_credentials and value == masked_credentials[name]:
                    credentials[name] = decrypted_credentials[name]

        try:
            provider_controller.validate_credentials_format(credentials)
            # get tool
            tool = provider_controller.get_tool(tool_name)
            tool = tool.fork_tool_runtime(
                runtime={
                    "credentials": credentials,
                    "tenant_id": tenant_id,
                }
            )
            result = tool.validate_credentials(credentials, parameters)
        except Exception as e:
            return {"error": str(e)}

        return {"result": result or "empty response"}

    @staticmethod
    def list_api_tools(user_id: str, tenant_id: str) -> list[UserToolProvider]:
        """
        list api tools
        """
        # get all api providers
        db_providers: list[PublicToolProvider] = (
            db.session.query(PublicToolProvider).filter(PublicToolProvider.tenant_id == tenant_id).all() or []
        )
        print("db_providers", db_providers)
        result: list[UserToolProvider] = []

        for provider in db_providers:
            # convert provider controller to user provider
            provider_controller = ToolTransformService.public_provider_to_controller(db_provider=provider)
            labels = ToolLabelManager.get_tool_labels(provider_controller)
            user_provider = ToolTransformService.public_provider_to_user_provider(
                provider_controller, db_provider=provider, decrypt_credentials=True
            )
            user_provider.labels = labels

            # add icon
            ToolTransformService.repack_provider(user_provider)
            print("provider_controller", provider_controller, type(provider_controller))
            tools = provider_controller.get_tools(user_id=user_id, tenant_id=tenant_id)
            print("工具", tools)
            for tool in tools:
                user_provider.tools.append(
                    ToolTransformService.tool_to_user_tool(
                        tenant_id=tenant_id, tool=tool, credentials=user_provider.original_credentials, labels=labels
                    )
                )

            result.append(user_provider)

        return result
