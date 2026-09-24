"""后端运行配置 — 全部来自环境变量，密钥不落盘。

密钥管理铁律：API Key 只允许通过 .env / 环境变量注入，禁止写入代码或仓库。
内部使用：后端默认绑定 127.0.0.1（不对外监听），已通过 HOST/PORT 可配。

部署红线：本服务**必须单进程部署**（uvicorn 不要加 --workers、不要多实例共享
同一 SQLite）。任务队列认领、WebSocket 进度订阅、登录限速器都是进程内存态，
多进程会直接分裂（任务被跑两遍 / 限速形同虚设）。并发调节用 WORKER_COUNT。
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # 读取 backend/.env（含 LLM 密钥，本地专用，不提交）

# 域引擎默认路径：与本项目同仓（分析skill = 内核 + 应用 完整项目），
# 默认指向项目根（backend/app/settings.py 向上两级）；可用 ENGINE_DIR 覆盖。
DEFAULT_ENGINE_DIR = str(Path(__file__).resolve().parents[2])


class Settings:
    def __init__(self) -> None:
        self.llm_provider: str = os.environ.get("LLM_PROVIDER", "mock").lower()

        # OpenAI
        self.openai_api_key: str = os.environ.get("OPENAI_API_KEY", "")
        self.openai_base_url: str = os.environ.get("OPENAI_BASE_URL", "")
        self.openai_model: str = os.environ.get("OPENAI_MODEL", "gpt-4o")

        # DeepSeek（OpenAI 兼容协议）
        self.deepseek_api_key: str = os.environ.get("DEEPSEEK_API_KEY", "")
        self.deepseek_base_url: str = os.environ.get(
            "DEEPSEEK_BASE_URL", "https://api.deepseek.com"
        )
        self.deepseek_model: str = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

        self.engine_dir: str = os.environ.get("ENGINE_DIR", DEFAULT_ENGINE_DIR)

        # 报告输出目录：默认 backend/generated；若显式配置则优先，
        # 且相对路径一律按 backend 根目录解析为绝对路径，避免产物散落在当前工作目录。
        default_gen = str(Path(__file__).resolve().parent.parent / "generated")
        gen_env = (os.environ.get("GENERATED_DIR") or "").strip()
        if gen_env:
            gen_path = Path(gen_env)
            if not gen_path.is_absolute():
                gen_path = Path(__file__).resolve().parent.parent / gen_path
            self.generated_dir = str(gen_path)
        else:
            self.generated_dir = default_gen

        # 内部使用：默认只监听本机回环地址，不对外暴露
        self.host: str = os.environ.get("HOST", "127.0.0.1")
        self.port: int = int(os.environ.get("PORT", "8000"))

        # —— 跨域放行来源（A1：由硬编码改为可配置）——
        # 默认放行本地两个前端：工作台 3000 + 独立运营后台 3001
        # （localhost 与 127.0.0.1 各自都放行；预览面板可能用 127.0.0.1）。
        # 对外部署时用 CORS_ORIGINS 覆盖（逗号分隔），例如：
        #   CORS_ORIGINS=https://app.example.com,https://admin.example.com
        # 注意：因为要带 cookie（credentials），这里的来源必须是精确值，不能用 "*"。
        _default_cors = (
            "http://localhost:3000,http://127.0.0.1:3000,"
            "http://localhost:3001,http://127.0.0.1:3001"
        )
        self.cors_origins: list[str] = [
            origin.strip()
            for origin in os.environ.get("CORS_ORIGINS", _default_cors).split(",")
            if origin.strip()
        ]

        # —— 公共部署模式（对外公测/多用户）：开启后 resolve_config 不再回退
        # 服务器 .env / 全局 store 的密钥，所有访客必须自带 API Key（BYOK），
        # 防止服务器管理员遗留的密钥被公共流量白嫖。
        # 同时决定默认归属人取值，故在此提前计算（原位置在本段之后）。
        self.public_mode: bool = (
            os.environ.get("PUBLIC_MODE", "").strip().lower() in {"1", "true", "yes", "on"}
        )

        # 默认项目归属人。默认取工作台品牌名，不在界面暴露作者个人姓名；
        # 需要固定归属人时显式配置 DEFAULT_OWNER_NAME / DEFAULT_OWNER_ID 即可（优先级最高）。
        self.default_owner_name: str = os.environ.get(
            "DEFAULT_OWNER_NAME", "引力矩阵"
        )
        self.default_owner_id: str = os.environ.get(
            "DEFAULT_OWNER_ID", "workbench"
        )

        # —— 注册邮箱验证（Phase 1）：SMTP 发信配置，不配 = 验证功能关闭 ——
        # QQ 邮箱示例：SMTP_HOST=smtp.qq.com / SMTP_PORT=465 / SMTP_USER=你的QQ邮箱 /
        # SMTP_PASS=授权码（不是登录密码）/ SMTP_SENDER 缺省取 SMTP_USER。
        # 未配置时注册直接视为已验证，注册/登录流程零变化。
        self.smtp_host: str = os.environ.get("SMTP_HOST", "").strip()
        self.smtp_port: int = int(os.environ.get("SMTP_PORT", "465"))
        self.smtp_user: str = os.environ.get("SMTP_USER", "").strip()
        self.smtp_pass: str = os.environ.get("SMTP_PASS", "").strip()
        self.smtp_sender: str = os.environ.get("SMTP_SENDER", "").strip() or self.smtp_user
        self.smtp_enabled: bool = bool(self.smtp_host and self.smtp_user and self.smtp_pass)

        # —— GitHub OAuth 登录（Phase 3）：配了 Client ID/Secret 才启用 ——
        # GitHub → Settings → Developer settings → OAuth Apps → New OAuth App；
        # Authorization callback URL 填 {后端基址}/api/auth/github/callback
        # （本地即 http://127.0.0.1:8000/api/auth/github/callback；反代部署时按公网后端地址填）。
        # 未配置时 /api/auth/github/* 返回 404，前端按钮自动隐藏，流程零变化。
        self.github_client_id: str = os.environ.get("GITHUB_CLIENT_ID", "").strip()
        self.github_client_secret: str = os.environ.get("GITHUB_CLIENT_SECRET", "").strip()
        self.github_oauth_enabled: bool = bool(self.github_client_id and self.github_client_secret)
        # 回调地址默认按请求本身推导（本地/反代都成立）；反代不传 Host 时可用它覆盖。
        self.github_redirect_uri: str = os.environ.get("GITHUB_REDIRECT_URI", "").strip()

        # —— 账户恢复流（忘记密码）——
        # 重置链接的前端基址：本地默认工作台 3000；对外部署时设为公网地址
        # （例如 PUBLIC_BASE_URL=https://app.example.com）。
        self.public_base_url: str = os.environ.get(
            "PUBLIC_BASE_URL", "http://127.0.0.1:3000"
        ).rstrip("/")
        # 本地调试开关：SMTP 未配置时，允许 forgot-password 接口把重置链接回显在响应里
        # （否则链接只进后端日志）。**默认关闭；公网实例务必保持关闭**，
        # 否则任何人都能凭邮箱直接拿到重置链接。
        self.dev_reset_echo: bool = (
            os.environ.get("AUTH_DEV_RESET_ECHO", "").strip().lower() in {"1", "true", "yes", "on"}
        )

        # —— 全网搜索（T1：检索源自动选择 BING_KEY → BRAVE_KEY → DDG 零 Key）——
        # 兼容旧字段（SEARCH_PROVIDER / SEARCH_API_KEY 仍在，供旧调用方使用）；
        # 新检索策略统一走 search_strategy 自动选择，不再要求必须配置 Key。
        self.search_provider: str = os.environ.get("SEARCH_PROVIDER", "serper").lower()
        self.search_api_key: str = os.environ.get("SEARCH_API_KEY", "")
        self.search_max_results: int = int(os.environ.get("SEARCH_MAX_RESULTS", "5"))
        # 灰度总开关：on=强制开放 / off=全局关停（前端隐藏开关、后端一律跳过）/ auto=默认（有 key 才可用）
        self.search_enabled: str = os.environ.get("SEARCH_ENABLED", "auto").lower()
        # —— T1：BING / BRAVE 官方 API Key（可选，配了自动升级；不配则回退 DDG HTML 零 Key）——
        self.bing_search_key: str = os.environ.get("BING_SEARCH_KEY", "").strip()
        self.brave_search_key: str = os.environ.get("BRAVE_SEARCH_KEY", "").strip()
        # 检索策略：auto(默认，BING→BRAVE→DDG 自动降级) | bing | brave | duckduckgo
        self.search_strategy: str = os.environ.get("SEARCH_STRATEGY", "auto").lower()

        # —— S2 全局舆情流（feed 最小闭环）——
        # FEED_ENABLED 默认 0：路由注册但统一返回 feed_disabled、调度不采集，
        # 对既有产品形态零回归；数据源配好后在 .env 显式开 1。
        self.feed_enabled: bool = (
            os.environ.get("FEED_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}
        )
        # 采集间隔（分钟）：挂既有 monitoring 调度循环，节流执行，不新开线程。
        self.feed_interval_min: int = int(os.environ.get("FEED_INTERVAL_MIN", "15"))

    @property
    def search_configured(self) -> bool:
        """是否具备可用的检索能力（T1 起：DDG HTML 零 Key 恒可执行）。

        只要检索策略未被显式钉死到某个需要 Key 的源，就视为可用；
        bing/brave 策略但缺对应 Key 时视为不可用（调用方应降级提示）。
        """
        if self.search_strategy == "bing":
            return bool(self.bing_search_key)
        if self.search_strategy == "brave":
            return bool(self.brave_search_key)
        return True  # auto / duckduckgo：零 Key 恒可用

    @property
    def search_available(self) -> bool:
        """搜索特性是否对用户开放（灰度总开关）。

        - off：全局关停，前端隐藏「联网搜索」开关、后端一律走 search_skipped；
        - auto / on：开放（实际运行仍要求 search_configured 且有 key，否则降级跳过）。
        用于「可灰度」逐步放量：先 off 观察稳定性，再 auto 对早期用户开放，最终常开。
        """
        return self.search_enabled != "off"

    @property
    def use_real_llm(self) -> bool:
        if self.llm_provider == "deepseek":
            return bool(self.deepseek_api_key)
        if self.llm_provider == "openai":
            return bool(self.openai_api_key)
        return False


settings = Settings()
