"""
EchoMind 智能客服系统 — FastAPI 入口

启动时打印小熊饼干图案。
所有核心组件在 lifespan 中初始化，通过环境变量配置。
"""


"""
FastAPI = 后端框架
@app.get / @app.post = 注册接口
Swagger = 自动生成的接口测试网页
tags = Swagger 页面里的接口分组
Optional  = 可以是某类型，也可以是 None
Optional[str]=None 或 str
注册一个 POST /skills/reload 接口，请求来了执行 reload_skills()，并在 Swagger 里归到 Skills 分组。
"""
'''
isinstance(x, list)     x 是不是列表
not x                   x 是不是空/False
dict.get(k, default)    有 k 取 k，没有就用默认值
continue                跳过当前循环这一轮
getattr(obj, a, d)      取 obj.a，取不到用 d
any(...)                只要有一个 True 就 True
or                      左右任意一个成立就成立
'''


import asyncio
import logging
import os
import pathlib
import sys
import uuid
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Literal


_ROOT = str(pathlib.Path(__file__).parent.parent.resolve())
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Response, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import AwareDatetime, BaseModel, Field

load_dotenv()

logging.basicConfig(#配置日志系统的基本规则，配置level = INFO，format = 时间 + 级别 + 模块名 + 消息
#     class Dog:
#     age = 3

# print(getattr(Dog, "age"))结果为3
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),#去 logging 这个模块里，找名字叫 INFO （先找.env中的loglevel，如果没有的话为INFO）的属性
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

BANNER = r"""
    ʕ•ᴥ•ʔ  ʕ•ᴥ•ʔ  ʕ•ᴥ•ʔ
   ╔══════════════════════╗
   ║   EchoMind  v2.0     ║
   ║   智能客服 AI 系统    ║
   ╚══════════════════════╝
    ʕ•ᴥ•ʔ  ʕ•ᴥ•ʔ  ʕ•ᴥ•ʔ
"""

# ── 全局组件（lifespan 中初始化）─────────────────────────────────────────────
_orchestrator = None
_memory       = None
_tool_manager = None
_monitor      = None
_evaluator    = None
_skill_manager = None
_diagnosis_pipeline = None
#专门负责“读配置”，获得dict形式的配置包
#把这些值整理成一个配置包
# cfg 是这个配置包
# 后面的模块拿 cfg 去初始化
def _anthropic_cfg() -> Dict[str, Any]:
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        raise RuntimeError("未设置 ANTHROPIC_API_KEY")
    cfg: Dict[str, Any] = {
        "api_key":  key,
        "model":    os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022").strip(),
    }
    base_url = os.getenv("ANTHROPIC_BASE_URL", "").strip()
    if base_url:
        cfg["base_url"] = base_url
    return cfg


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _orchestrator, _memory, _tool_manager, _monitor, _evaluator, _skill_manager, _diagnosis_pipeline#我要修改外面的全局变量，需要做的是给none的东西赋值

    print(BANNER, flush=True)

    from agents.agent_orchestrator import AgentOrchestrator, Request
    from core.intent_recognizer import IntentRecognizer
    from evaluation.evaluator import EndToEndEvaluator
    from mcp.knowledge_base import KnowledgeBase
    from mcp.tool_manager import MCPToolManager, Tool
    from memory.conversation_memory import MemoryManager
    from monitor.performance_monitor import PerformanceMonitor
    from core.skill_loader import SkillManager
    from core.rootlens_config import memory_options, knowledge_collection
    from core.diagnosis_pipeline import DiagnosisPipeline
    from mcp.incident_tools import IncidentTools

    cfg = _anthropic_cfg()
    logger.info(f"模型: {cfg['model']}  base_url: {cfg.get('base_url', '(官方)')}")

    # 意图识别器（Orchestrator 内部也会创建，这里单独暴露给 Evaluator）
    recognizer = IntentRecognizer(
        api_key=cfg["api_key"],
        base_url=cfg.get("base_url"),
        model=cfg["model"],
    )

    # Skills：启动时从目录加载业务能力说明，并在 Agent 调用 LLM 时动态注入。系统知道有哪些客服规则可以注入给 Agent
    skills_dir = os.getenv("ECHOMIND_SKILLS_DIR", str(pathlib.Path(_ROOT) / "skills"))
    _skill_manager = SkillManager(
        root_dir=skills_dir,
        max_prompt_chars=int(os.getenv("ECHOMIND_SKILLS_MAX_PROMPT_CHARS", "5000")),
    )
    _skill_manager.load()#把这些规则读进来

    # Agent 编排器
    _orchestrator = AgentOrchestrator(
        api_key=cfg["api_key"],
        base_url=cfg.get("base_url"),
        model=cfg["model"],
        skill_manager=_skill_manager,
        #为什么要传 skill_manager？因为 Agent 生成回复时需要把对应规则注入 prompt。
    )

    # 记忆管理器（Redis 工作记忆 + ChromaDB 情景记忆/用户画像），记忆需要LLM是因为这个过程压缩1记忆什么的也需要LLM
    _memory = MemoryManager(
        redis_url=os.getenv("REDIS_URL", "redis://redis:6379/0"),
        chroma_host=os.getenv("CHROMA_HOST", "chromadb"),
        chroma_port=int(os.getenv("CHROMA_PORT", "8000")),
        chroma_path=os.getenv("CHROMA_PERSIST_DIRECTORY", "/app/data/chroma"),
        api_key=cfg["api_key"],
        base_url=cfg.get("base_url"),
        model=cfg["model"],
        **memory_options(),
    )

    # MCP 工具管理器 + RAG 知识库（基于 ChromaDB 的真实检索）
    _tool_manager = MCPToolManager(
        api_key=cfg["api_key"],
        base_url=cfg.get("base_url"),
        model=cfg["model"],
    )
    kb = KnowledgeBase(
        chroma_host=os.getenv("CHROMA_HOST", "chromadb"),
        chroma_port=int(os.getenv("CHROMA_PORT", "8000")),
        chroma_path=os.getenv("CHROMA_PERSIST_DIRECTORY", "/app/data/chroma"),
        collection_name=knowledge_collection(),
        load_default_docs=False,
        max_distance=float(os.getenv("ROOTLENS_KNOWLEDGE_MAX_DISTANCE", "0.8")),
    )
    await asyncio.to_thread(kb.load_rootlens_documents)
    logger.info(f"知识库已加载: {await kb.doc_count_async()} 个文档片段")
    #给工具管理器注册 knowledge_search,这个函数是降级方案。如果知识库检索失败，不是直接崩，而是返回一条“知识库暂时不可用”的结果
    def knowledge_fallback(params: Dict[str, Any], context: Optional[Dict[str, Any]], error: str):
        query = params.get("query", "")
        return [{
            "title": "知识库降级结果",
            "content": f"知识库暂时不可用，未能完成对“{query}”的语义检索。该降级说明不是故障处置知识。",
            "score": 0.0,
            "fallback": True,
            "error": error,
        }]
    #Tool= 把“查 ChromaDB”包装成一个标准工具
# _tool_manager.register(Tool(...))
# = 给工具管理器登记一个工具。

# 这个工具叫 knowledge_search。
# 它的实际执行函数是 kb.search_handler。
# ToolManager 以后只要按名字找到 knowledge_search，
# 就能统一处理参数校验、缓存、超时、熔断、fallback、统计和 rerank，
# 然后再调用 kb.search_handler 去真正查 ChromaDB。
    _tool_manager.register(Tool(
        name="knowledge_search",
        description="搜索知识库（基于 ChromaDB 向量检索）",
        handler=kb.search_handler,#tool.handler = kb.search_handler
        schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "top_k": {"type": "integer"},
            },
            "required": ["query"],
        },
        cache_ttl=300.0,# 缓存 300 秒
        supports_rerank=True,#支持重排
        fallback=knowledge_fallback,#出错时走降级函数
    ))

    incident_tools = IncidentTools()
    incident_tools.register(_tool_manager)
    _diagnosis_pipeline = DiagnosisPipeline(
        orchestrator=_orchestrator, tool_manager=_tool_manager,
        knowledge_lookup=_retrieve_knowledge_context,
        dataset_id=incident_tools.manifest.dataset_id,
        dataset_version=incident_tools.manifest.dataset_version,
        timezone=incident_tools.manifest.timezone,
    )

    # 性能监控（可选启动 Prometheus）
    prom_port = int(os.getenv("PROMETHEUS_PORT", "0")) or None
    _monitor = PerformanceMonitor(
        orchestrator=_orchestrator,
        tool_manager=_tool_manager,
        interval_s=float(os.getenv("MONITOR_INTERVAL", "10")),
        webhook_url=os.getenv("ALERT_WEBHOOK_URL") or None,
        prometheus_port=prom_port,
    )
    await _monitor.start()

    # 评测器
    _evaluator = EndToEndEvaluator(
        orchestrator=_orchestrator,
        recognizer=recognizer,
        api_key=cfg["api_key"],
        base_url=cfg.get("base_url"),
        model=cfg["model"],
        baseline_path=os.getenv("EVAL_BASELINE_PATH", "/app/data/eval/baseline.json"),
    )

    logger.info("EchoMind 已就绪")
    yield

    await _monitor.stop()
    if _memory is not None:
        await _memory.close()
    logger.info("EchoMind 已关闭")


# ── FastAPI ───────────────────────────────────────────────────────────────────
app = FastAPI(
    title="EchoMind 智能客服",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs",
)
#让前端网页可以调用这个后端接口
app.add_middleware(
    # 允许任意来源访问
    # 允许任意 HTTP 方法
    # 允许任意请求头
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 请求/响应模型 ─────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message:     str
    user_id:     str = "anonymous"
    conv_id:     Optional[str] = None#这个值可以是某种类型，也可以是 None
    environment: Optional[Literal["demo", "staging", "prod"]] = None
    anchor_time: Optional[AwareDatetime] = None


class ChatResponse(BaseModel):
    conv_id:     str
    response:    str
    intent:      str
    intent_group: str = "other"
    agent_type:  str
# =[] 
# 像是所有人共用一个购物袋
# Field(default_factory=list)
# 像是每个人来时都新发一个购物袋


# 所以默认值如果是 str / int / float / bool / None，直接写通常没问题。

# 默认值如果是 list / dict / set，优先用 default_factory。
    agent_types: List[str] = Field(default_factory=list)#每次创建 ChatResponse 时，都新建一个空列表,Field是Pydantic提供的一个字段配置函数
    primary_agent: str = ""
    supporting_agents: List[str] = Field(default_factory=list)
    routing_reason: str = ""
    routing_confidence: float = 0.0
    escalated:   bool
    latency_ms:  float
    knowledge_used: bool = False
    entities: Dict[str, List[str]] = Field(default_factory=dict)#每次创建 ChatResponse 时，都新建一个空字典
    intent_confidence: float = 0.0
    intent_source_scores: Dict[str, float] = Field(default_factory=dict)
    evidence_ids: List[str] = Field(default_factory=list)
    tool_status: Dict[str, str] = Field(default_factory=dict)
    tool_errors: Dict[str, str] = Field(default_factory=dict)
    query_context: Optional[Dict[str, Any]] = None
    rag_stage_status: Dict[str, str] = Field(default_factory=dict)
    evidence_entities: Dict[str, List[str]] = Field(default_factory=dict)
    routing_signal_sources: Dict[str, List[str]] = Field(default_factory=dict)
    clarification_required: bool = False


# ── 路由 ──────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    if _orchestrator is None:
        raise HTTPException(503, "服务未就绪")
    return {"status": "ok", "agents": _orchestrator.get_stats()}


@app.get("/skills", tags=["Skills"])
async def skills_summary():
    """查看当前已加载的 Skills，便于确认热加载结果和排查解析错误。"""
    if _skill_manager is None:
        raise HTTPException(503, "Skills 未初始化")
    return _skill_manager.summary()


@app.post("/skills/reload", tags=["Skills"])
async def reload_skills():
    """运行时重新扫描 Skill 目录，不需要重启服务。"""
    if _skill_manager is None:
        raise HTTPException(503, "Skills 未初始化")
    _skill_manager.reload()
    if _orchestrator is not None:
        _orchestrator.set_skill_manager(_skill_manager)
    return _skill_manager.summary()


# 注册一个 POST /chat 接口
# 请求来了就调用下面这个 chat 函数
# 返回结果按 ChatResponse 整理/校验
@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):#我要把用户 POST 过来的 JSON 请求体解析成 ChatRequest 对象，然后传给这个req参数
    """
    主对话接口。完整流程：
    记忆读取 → 意图识别 → Agent 路由 → 执行 → 记忆写入
    """
    if _orchestrator is None or _memory is None or _diagnosis_pipeline is None:
        raise HTTPException(503, "服务未就绪")

    from memory.conversation_memory import MsgRole

    conv_id = req.conv_id or str(uuid.uuid4())

    # 1. 读取记忆上下文
    mem_ctx = await _memory.get_context(req.user_id, conv_id, query=req.message)

    # 2. 构建编排请求（含对话历史，用于意图识别上下文）
    history = [
        {"role": m.role.value, "content": m.content}
        for m in mem_ctx.recent_messages[-5:]
    ] if mem_ctx.recent_messages else None

    intent_result = await _orchestrator.recognize_intent(req.message, history=history)
    outcome = await _diagnosis_pipeline.run(
        message=req.message, user_id=req.user_id, conv_id=conv_id,
        memory_context=mem_ctx.to_prompt_text(), history=history,
        intent_result=intent_result, environment=req.environment,
        anchor_time=req.anchor_time,
    )
    result = outcome.result
    bundle = outcome.bundle

    # 4. 写入记忆
    await _memory.add_message(req.user_id, conv_id, MsgRole.USER, req.message)
    await _memory.add_message(req.user_id, conv_id, MsgRole.ASSISTANT, result.response)

    # 5. 异步更新用户画像（不阻塞响应）
    if _memory.enable_user_profile:
        asyncio.create_task(_memory.update_profile(req.user_id, conv_id))

    return ChatResponse(
        conv_id=conv_id,
        response=result.response,
        intent=result.intent.value if result.intent else "other",
        intent_group=intent_result.intent_group,
        agent_type=result.agent_type.value,
        agent_types=[agent_type.value for agent_type in result.agent_types],
        primary_agent=(result.primary_agent.value if result.primary_agent else
                       "" if outcome.clarification_required else result.agent_type.value),
        supporting_agents=[agent_type.value for agent_type in result.supporting_agents],
        routing_reason=result.routing_reason,
        routing_confidence=result.routing_confidence,
        escalated=result.escalated,
        latency_ms=round(result.latency_ms, 1),
        knowledge_used=outcome.knowledge.used,
        entities=intent_result.entities,
        intent_confidence=round(intent_result.confidence, 4),
        intent_source_scores=intent_result.source_scores,
        evidence_ids=[item.evidence_id for item in bundle.evidence] if bundle else [],
        tool_status={name: state.status for name, state in bundle.tool_status.items()} if bundle else {},
        tool_errors={name: state.error for name, state in bundle.tool_status.items()
                     if state.error} if bundle else {},
        query_context=bundle.query_context.model_dump(mode="json") if bundle else None,
        rag_stage_status=outcome.knowledge.stages,
        evidence_entities=outcome.signals.entities,
        routing_signal_sources=outcome.signals.evidence_ids,
        clarification_required=outcome.clarification_required,
    )


async def _build_knowledge_context(message: str, intent=None, top_k: int = 3) -> tuple[str, bool]:
    """
    为 /chat 主链路构建 RAG 知识上下文。

    这里复用 MCPToolManager 的查询改写、并行召回、重排、fallback 能力。
    """
    if not _should_use_knowledge(message, intent=intent):
        return "", False
    knowledge = await _retrieve_knowledge_context(message, top_k=top_k)
    return knowledge.text, knowledge.used


async def _retrieve_knowledge_context(message: str, top_k: int = 3):
    from core.diagnosis_pipeline import KnowledgeResult, KnowledgeSource
    if _tool_manager is None:
        return KnowledgeResult(stages={"rewrite": "skipped", "retrieval": "failed", "rerank": "skipped"})
    try:
        result = await _tool_manager.search_with_rewrite("knowledge_search", message, top_k=top_k)
        stages = {"rewrite": result.rewrite_status, "retrieval": result.retrieval_status,
                  "rerank": result.rerank_status}
        if not result.success or not isinstance(result.data, list) or not result.data:
            return KnowledgeResult(stages=stages)

        parts = ["[知识库检索结果]"]
        used = False
        sources = []
        for i, item in enumerate(result.data[:top_k], start=1):
            if (not isinstance(item, dict) or item.get("fallback")
                    or not item.get("chunk_id") or not item.get("source_ref")):
                continue
            title = str(item.get("title", "未命名文档"))#字典.get("键名", 默认值)得到字典的值
            content = str(item.get("content", "")).strip()
            score = item.get("score", "")
            if not content:
                continue
            used = True
            parts.append(f"{i}. 标题: {title}\n   来源: {item['source_ref']} ({item['chunk_id']})\n   相关度: {score}\n   内容: {content[:600]}")
            if item.get("document_id"):
                sources.append(KnowledgeSource(
                    document_id=str(item["document_id"]),
                    chunk_id=str(item["chunk_id"]),
                    source_ref=str(item["source_ref"]),
                ))

        if not used:
            return KnowledgeResult(stages=stages)
        parts.append("以上是处置规则或历史经验，不是本次现场事实；知识不足时明确说明，不推断唯一根因。")
        return KnowledgeResult(text="\n".join(parts), used=True, stages=stages,
                               sources=sources)
    except Exception as ex:
        logger.warning(f"构建知识库上下文失败: {ex}")
        return KnowledgeResult(stages={"rewrite": "failed", "retrieval": "failed", "rerank": "skipped"})


def _should_use_knowledge(message: str, intent=None) -> bool:#intent: Optional[str] = None,intent 这个参数，类型可以是 str，也可以是 None。如果调用函数时不传 intent，它默认就是 None。
    """跳过纯寒暄，业务类问题才检索知识库，避免无关 RAG 干扰回复。"""
    msg = (message or "").strip().lower()
    if not msg:
        return False
    intent_value = getattr(intent, "value", intent)#getattr(对象, "属性名", 默认值)   也就是说如果 intent 有 .value 属性，就取 intent.value，如果没有 .value 属性，就直接用 intent 自己
    if intent_value in {"greeting", "feedback", "escalation", "human_handoff", "other"}:
        return False
    if intent_value in {
        "query", "request", "technical", "billing", "account", "complaint",
        "order_status", "logistics", "refund", "invoice", "payment_issue",
        "account_security", "technical_login", "technical_crash",
    }:
        return True
    greetings = {"你好", "您好", "嗨", "hi", "hello", "hey", "早上好", "晚上好"}
    if msg in greetings:
        return False
    business_keywords = [
        "退款", "订单", "物流", "配送", "发票", "扣款", "支付", "账单", "订阅",
        "登录", "报错", "错误", "崩溃", "会员", "积分", "账户", "密码", "地址",
        "refund", "order", "invoice", "payment", "error", "login",
    ]
    return len(msg) >= 4 or any(kw in msg for kw in business_keywords)#any() 的意思是只要里面有一个 True，整体就是 True


@app.get("/monitor")
async def monitor_summary():
    """实时监控摘要：Agent 成功率、工具统计、告警、优化建议。"""
    if _monitor is None:
        raise HTTPException(503, "服务未就绪")
    return _monitor.summary()


@app.get("/metrics")
async def prometheus_metrics():
    """Prometheus 指标入口。"""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/search")
async def search(query: str, top_k: int = 5):
    """
    演示检索优化链路：查询改写 → 并行召回 → 重排 → Top-K。
    展示 MCP 工具调用的核心亮点。
    """
    if _tool_manager is None:
        raise HTTPException(503, "服务未就绪")
    result = await _tool_manager.search_with_rewrite("knowledge_search", query, top_k=top_k)
    return {"query": query, "results": result.data, "reranked": result.reranked,
            "success": result.success, "error": result.error,
            "rewrite_status": result.rewrite_status, "retrieval_status": result.retrieval_status,
            "rerank_status": result.rerank_status, "stage_errors": result.stage_errors}


class DocInput(BaseModel):
    """单篇文档输入。"""
    title:   str
    content: str


class BatchDocInput(BaseModel):
    """批量文档导入请求体。"""
    documents: List[DocInput]


class EvalIntentInput(BaseModel):
    """意图识别评测用例。"""
    message: str
    expected_intent: str
    context: Optional[Dict[str, Any]] = None


class EvalDialogInput(BaseModel):
    """对话质量评测用例。question 单轮，turns 多轮。"""
    question: Optional[str] = None
    turns: Optional[List[str]] = None
    user_id: Optional[str] = None
    conv_id: Optional[str] = None


class EvalRunInput(BaseModel):
    """评测请求。为空时使用内置默认用例。"""
    intent_cases: Optional[List[EvalIntentInput]] = None
    dialog_cases: Optional[List[EvalDialogInput]] = None


@app.post("/knowledge/add", tags=["知识库"])
async def add_knowledge(body: BatchDocInput):
    """
    批量导入文档到知识库。

    文档会自动切片（每片 500 字）并存入 ChromaDB，ChromaDB 内置 Embedding 模型自动向量化。

    示例请求体：
    ```json
    {
      "documents": [
        {"title": "退款政策", "content": "用户在购买后 7 天内可以申请无理由退款..."},
        {"title": "配送说明", "content": "标准配送 3-5 个工作日..."}
      ]
    }
    ```
    """
    tool = _tool_manager._tools.get("knowledge_search") if _tool_manager else None
    if tool is None:
        raise HTTPException(503, "知识库未初始化")
    kb = tool.handler.__self__
    count = await kb.add_documents_async([{"title": d.title, "content": d.content} for d in body.documents])
    total = await kb.doc_count_async()
    return {"message": f"成功导入 {count} 个文档片段", "added_chunks": count, "total_chunks": total}


@app.post("/knowledge/upload", tags=["知识库"])
async def upload_knowledge(file: UploadFile = File(...)):
    """
    上传文件导入知识库。

    支持格式：
    - `.txt` / `.md`：整个文件作为一篇文档，文件名作为标题
    - `.json`：JSON 数组格式 `[{"title": "...", "content": "..."}, ...]`

    文件大小限制：10MB
    """
    tool = _tool_manager._tools.get("knowledge_search") if _tool_manager else None
    if tool is None:
        raise HTTPException(503, "知识库未初始化")
    kb = tool.handler.__self__#tool.handler本质上就是kb.search_handler，__self__就相当于找到了前面的那个, kb.search_handler 这个绑定方法里，把 kb 对象取回来

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(413, "文件大小超过 10MB 限制")

    text = content.decode("utf-8", errors="ignore")
    filename = file.filename or "unknown"

    if filename.endswith(".json"):
        import json as _json
        try:
            docs = _json.loads(text)
            if not isinstance(docs, list):
                raise HTTPException(400, "JSON 文件应为数组格式: [{title, content}, ...]")
        except _json.JSONDecodeError as e:
            raise HTTPException(400, f"JSON 解析失败: {e}")
    else:
        # txt / md：整个文件作为一篇文档
        title = filename.rsplit(".", 1)[0] if "." in filename else filename
        docs = [{"title": title, "content": text}]

    count = await kb.add_documents_async(docs)
    total = await kb.doc_count_async()
    return {
        "message": f"文件 {filename} 导入成功",
        "added_chunks": count,
        "total_chunks": total,
    }


@app.get("/knowledge/stats", tags=["知识库"])
async def knowledge_stats():
    """查看知识库统计信息（文档片段总数）。"""
    tool = _tool_manager._tools.get("knowledge_search") if _tool_manager else None
    if tool is None:
        raise HTTPException(503, "知识库未初始化")
    kb = tool.handler.__self__
    return {"total_chunks": await kb.doc_count_async()}


@app.post("/eval/run")
async def run_eval(body: Optional[EvalRunInput] = None):
    """运行内置评测用例，返回评测报告。"""
    if _evaluator is None:
        raise HTTPException(503, "服务未就绪")
    from evaluation.evaluator import DEFAULT_DIALOG_CASES, DEFAULT_INTENT_CASES, IntentTestCase

    if body and body.intent_cases is not None:
        intent_cases = [
            IntentTestCase(
                message=c.message,
                expected_intent=c.expected_intent,
                context=c.context,
            )
            for c in body.intent_cases
        ]
    else:
        intent_cases = DEFAULT_INTENT_CASES

    if body and body.dialog_cases is not None:
        dialog_cases = [
            c.model_dump(exclude_none=True)
            for c in body.dialog_cases
        ]
    else:
        dialog_cases = DEFAULT_DIALOG_CASES

    report = await _evaluator.run(
        intent_cases=intent_cases,
        dialog_cases=dialog_cases,
    )
    return {
        "pass_rate":       report.pass_rate,
        "total":           report.total,
        "passed":          report.passed,
        "avg_scores":      report.avg_scores,
        "regressions":     report.regressions,
        "recommendations": report.recommendations,
        "results": [
            {
                "test_id": r.test_id,
                "passed": r.passed,
                "scores": r.scores,
                "detail": r.detail,
                "metadata": r.metadata,
            }
            for r in report.results
        ],
    }


# ── 交互式 CLI ────────────────────────────────────────────────────────────────
async def _cli():
    print(BANNER)
    print("EchoMind CLI — 输入 quit 退出\n")

    from agents.agent_orchestrator import AgentOrchestrator, Request
    from memory.conversation_memory import MemoryManager, MsgRole
    from core.skill_loader import SkillManager

    cfg = _anthropic_cfg()
    skill_manager = SkillManager(
        root_dir=os.getenv("ECHOMIND_SKILLS_DIR", str(pathlib.Path(_ROOT) / "skills")),
        max_prompt_chars=int(os.getenv("ECHOMIND_SKILLS_MAX_PROMPT_CHARS", "5000")),
    )
    skill_manager.load()
    orch = AgentOrchestrator(
        api_key=cfg["api_key"],
        base_url=cfg.get("base_url"),
        model=cfg["model"],
        skill_manager=skill_manager,
    )
    mem  = MemoryManager(
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        chroma_host=os.getenv("CHROMA_HOST", "localhost"),
        chroma_port=int(os.getenv("CHROMA_PORT", "8000")),
        chroma_path=os.getenv("CHROMA_PERSIST_DIRECTORY", "/tmp/chroma"),
        api_key=cfg["api_key"],
        base_url=cfg.get("base_url"),
        model=cfg["model"],
    )

    user_id, conv_id = "cli_user", str(uuid.uuid4())

    while True:
        try:
            msg = input("你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见 ʕ•ᴥ•ʔ")
            break
        if not msg or msg.lower() in ("quit", "exit", "退出"):
            print("再见 ʕ•ᴥ•ʔ")
            break

        ctx = await mem.get_context(user_id, conv_id, query=msg)
        history = [
            {"role": m.role.value, "content": m.content}
            for m in ctx.recent_messages[-5:]
        ] if ctx.recent_messages else None
        req = Request(message=msg, user_id=user_id, conv_id=conv_id, context=ctx.to_prompt_text(), history=history)
        result = await orch.run(req)

        await mem.add_message(user_id, conv_id, MsgRole.USER, msg)
        await mem.add_message(user_id, conv_id, MsgRole.ASSISTANT, result.response)

        print(f"\nEchoMind [{result.agent_type.value}]: {result.response}\n")

    await mem.close()


if __name__ == "__main__":
    if "--cli" in sys.argv:
        asyncio.run(_cli())
    else:
        uvicorn.run(
            "api.main:app",
            host=os.getenv("API_HOST", "0.0.0.0"),
            port=int(os.getenv("API_PORT", "8000")),
            reload=os.getenv("APP_ENV") == "development",
        )
