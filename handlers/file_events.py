"""文件上传事件处理器"""

from astrbot.api import logger


class FileEventHandler:
    """群文件上传事件监听处理"""

    def __init__(self, plugin):
        self._plugin = plugin

    @property
    def config(self):
        return self._plugin.config

    @property
    def filename_checker(self):
        return self._plugin.filename_checker

    @property
    def naming_validator(self):
        return getattr(self._plugin, 'naming_validator', None)

    @property
    def notify_service(self):
        return self._plugin.notify_service

    async def handle_file_upload(self, event):
        """监听群文件上传消息，检测文件名是否合规

        支持两种命名规范：
        1. 新格式：项目名称-分类v版本号-后缀.扩展名
        2. 旧格式（兼容）：分类--名称.扩展名
        """
        logger.info("========== 收到群消息，检测文件上传 ==========")

        # 检查配置状态
        if not self.config:
            logger.warning("配置为空，跳过文件名检查")
            return

        if not self.config.filename_check_enabled:
            logger.info("文件名检查未启用，跳过")
            return

        # 优先使用新 NamingValidator
        checker = self.naming_validator or self.filename_checker
        if not checker or not self.notify_service:
            logger.warning("文件名检查器或通知服务未初始化，跳过")
            return

        # 检查群号是否在启用列表中
        group_id = event.get_group_id()
        if group_id:
            enabled = self.config.enabled_groups
            if enabled and group_id not in enabled:
                logger.info(f"群 {group_id} 不在启用列表中，跳过文件名检查")
                return

        # 检查消息中是否包含 File 组件
        import astrbot.api.message_components as Comp
        file_component = None
        message_chain = event.message_obj.message
        logger.info(f"消息链长度: {len(message_chain)}")

        for i, seg in enumerate(message_chain):
            seg_type = type(seg).__name__
            logger.debug(f"  消息段[{i}]: {seg_type}")
            if isinstance(seg, Comp.File):
                file_component = seg
                logger.info(f"  找到 File 组件: {seg_type}")
                break

        if not file_component:
            logger.info("消息中不包含 File 组件，跳过文件检查")
            return

        # 获取文件名
        filename = getattr(file_component, 'name', None) or getattr(file_component, 'file', None)
        logger.info(f"从 File 组件提取文件名: {filename}")

        if not filename:
            raw = event.message_obj.raw_message
            if raw and isinstance(raw, dict):
                file_data = raw.get('file', {})
                if isinstance(file_data, dict):
                    filename = file_data.get('name')
                if not filename:
                    filename = raw.get('filename')

        if not filename:
            logger.warning("无法获取文件名，跳过检查")
            return

        logger.info(f"开始检查文件名: {filename}")

        # 判断使用新 NamingValidator 还是旧的 FilenameChecker
        if self.naming_validator:
            result = self.naming_validator.validate(
                filename=filename,
                sender_id=event.get_sender_id(),
                sender_name=event.get_sender_name(),
                group_id=event.get_group_id() or ""
            )
            logger.info(f"文件名检查完成: {filename}")
            logger.info(f"  - 是否合规: {result.is_valid}")
            logger.info(f"  - 提取的分类: {result.category}")
            if not result.is_valid:
                logger.info(f"  - 错误类型: {result.error_type}")
                logger.info(f"  - 错误原因: {result.error_reason}")
        else:
            # 兼容旧的 FilenameChecker（返回 FileValidationResult）
            result = self.filename_checker.validate(
                filename=filename,
                sender_id=event.get_sender_id(),
                sender_name=event.get_sender_name(),
                group_id=event.get_group_id() or ""
            )

        if not result.is_valid:
            if self.naming_validator:
                categories_str = self.naming_validator.format_categories()
            else:
                categories_str = (self.filename_checker.format_categories()
                                  if self.filename_checker else "")

            chain = self.notify_service.build_message_chain(result, categories_str)
            yield event.chain_result(chain)
            logger.info("@提醒消息已发送")
        else:
            logger.info("文件名合规，无需提醒")
