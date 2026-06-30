"""文件上传事件处理器

职责：监听群文件上传 → 命名检查 → 合规则即时同步到 NextCloud
"""

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
        """监听群文件上传消息

        流程：
        1. 命名合规 → 即时同步到 NextCloud，发送成功/失败结果
        2. 命名不合规 → @提醒用户修正
        3. 旧格式合规 → 即时同步 + 温和提醒迁移
        """
        logger.info("========== 收到群消息，检测文件上传 ==========")

        # 检查配置状态
        if not self.config:
            logger.warning("配置为空，跳过文件名检查")
            return

        if not self.config.filename_check_enabled:
            logger.info("文件名检查未启用，跳过")
            return

        checker = self.naming_validator or self.filename_checker
        if not checker or not self.notify_service:
            logger.warning("文件名检查器或通知服务未初始化，跳过")
            return

        # 检查群号白名单
        group_id = event.get_group_id()
        if group_id:
            enabled = self.config.enabled_groups
            if enabled and group_id not in enabled:
                logger.info(f"群 {group_id} 不在启用列表中，跳过文件名检查")
                return

        # 检查消息中是否包含 File 组件
        try:
            import astrbot.api.message_components as Comp
        except ImportError:
            logger.warning("无法导入 astrbot.api.message_components，跳过文件检查")
            return

        file_component = None
        message_chain = event.message_obj.message
        logger.info(f"消息链长度: {len(message_chain)}")

        for seg in message_chain:
            if isinstance(seg, Comp.File):
                file_component = seg
                break

        if not file_component:
            logger.info("消息中不包含 File 组件，跳过文件检查")
            return

        # 提取文件信息（file_id、文件名、文件大小）
        file_id = (
            getattr(file_component, 'id', None)
            or getattr(file_component, 'file_id', None)
            or getattr(file_component, 'fileid', None)
            or ""
        )
        file_size = getattr(file_component, 'size', None) or getattr(file_component, 'file_size', 0)

        filename = getattr(file_component, 'name', None) or getattr(file_component, 'file', None)
        logger.info(f"从 File 组件提取: name={filename}, file_id={file_id}, size={file_size}")

        if not filename:
            raw = event.message_obj.raw_message
            if raw and isinstance(raw, dict):
                file_data = raw.get('file', {})
                if isinstance(file_data, dict):
                    filename = file_data.get('name')
                if not filename:
                    filename = raw.get('filename')
                if not file_id:
                    file_id = file_data.get('id', '') if isinstance(file_data, dict) else ''

        if not filename:
            logger.warning("无法获取文件名，跳过检查")
            return

        logger.info(f"开始检查文件名: {filename}")

        # 使用 NamingValidator 校验命名
        if self.naming_validator:
            result = self.naming_validator.validate(
                filename=filename,
                sender_id=event.get_sender_id(),
                sender_name=event.get_sender_name(),
                group_id=group_id or ""
            )
            logger.info(f"文件名检查完成: {filename}")
            logger.info(f"  - 是否合规: {result.is_valid}")
            logger.info(f"  - 提取的分类: {result.category}")
            if not result.is_valid:
                logger.info(f"  - 错误类型: {result.error_type}")
                logger.info(f"  - 错误原因: {result.error_reason}")
        else:
            result = self.filename_checker.validate(
                filename=filename,
                sender_id=event.get_sender_id(),
                sender_name=event.get_sender_name(),
                group_id=group_id or ""
            )

        # ── 命名不合规 → 只发提醒，不触发同步 ──
        if not result.is_valid:
            categories_str = (self.naming_validator.format_categories()
                              if self.naming_validator else "")
            chain = self.notify_service.build_message_chain(result, categories_str)
            yield event.chain_result(chain)
            logger.info("文件名不合规，@提醒已发送，跳过同步")
            return

        # ── 命名合规 → 即时同步到 NextCloud ──
        if not group_id:
            logger.warning("无法获取群号，跳过即时同步")
            return
        if not file_id:
            logger.warning("无法获取 file_id，跳过即时同步")
            return

        logger.info(f"文件名合规，触发即时同步: {filename}")
        sync_result = await self._plugin.sync_uploaded_file(
            group_id=group_id,
            file_id=file_id,
            file_name=filename,
            file_size=file_size,
            sender_id=event.get_sender_id(),
            sender_name=event.get_sender_name(),
        )

        # ── 发送同步结果消息 ──
        try:
            import astrbot.api.message_components as Comp
        except ImportError:
            # 无 AstrBot 环境时直接输出日志
            logger.info(f"[UPLOAD_SYNC] 结果: filename={filename}, "
                        f"success={sync_result.success}, path={sync_result.target_path}")
            return

        target_path_prefix = sync_result.target_path.rsplit("/", 1)[0] if sync_result.target_path else ""

        if sync_result.success:
            yield event.chain_result([
                Comp.At(qq=event.get_sender_id()),
                Comp.Plain(text=f"文件「{filename}」已同步到网盘 ✓"),
                Comp.Plain(text=f"路径：{target_path_prefix}/"),
            ])
            logger.info(f"即时同步成功: {filename}")
        else:
            yield event.chain_result([
                Comp.At(qq=event.get_sender_id()),
                Comp.Plain(text=f"文件「{filename}」同步失败: {sync_result.failed_detail or sync_result.failed_stage}"),
            ])
            logger.warning(f"即时同步失败: {filename} - {sync_result.failed_stage}: {sync_result.failed_detail}")

        # ── 旧格式温和提醒（合规 + deprecated，在同步成功后附加）──
        deprecated = getattr(result, 'deprecated_separator', False)
        if deprecated and sync_result.success:
            try:
                import astrbot.api.message_components as Comp
            except ImportError:
                return

            yield event.chain_result([
                Comp.At(qq=event.get_sender_id()),
                Comp.Plain(text=f"你上传的文件「{filename}」使用了旧格式「分类--名称」"),
                Comp.Plain(text="⚠️ 该格式仍被接受，但建议迁移到新格式：项目名称-分类v版本号-后缀"),
            ])
            logger.info("旧格式温和提醒已发送")
