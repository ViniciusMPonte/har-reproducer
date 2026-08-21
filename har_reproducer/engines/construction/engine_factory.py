from pathlib import Path
from typing import ClassVar, Dict, Optional, Type

from langchain_core.language_models.chat_models import BaseChatModel

from har_reproducer.agents import AgentFactory
from har_reproducer.contracts import HttpTransport
from har_reproducer.engines.construction.engine_mode import EngineMode
from har_reproducer.engines.dry_engine import DryEngine
from har_reproducer.engines.engine import Engine
from har_reproducer.fs_io import Workspace
from har_reproducer.llm import LLMFactory
from har_reproducer.models import ProjectConfig
from har_reproducer.replay.curl_token_comment import CurlTokenComment
from har_reproducer.replay.replay_result_comparator import ReplayResultComparator
from har_reproducer.reproduction import (
    CurlGenerator,
    ExtractorMetadataStore,
    ExtractorRunner,
    ScriptExecutor,
    Sleeper,
    StepRetryPolicy,
    StepSkipEvaluator,
)
from har_reproducer.session import SessionStore
from har_reproducer.tracking import (
    BaselineDiff,
    CandidateResolver,
    FlowVocabulary,
    OriginFinder,
    PlaceholderApplier,
    ResponseCorpus,
    TokenResolver,
    TokenTracker,
)
from har_reproducer.validation import Validator


class EngineFactory:
    _STRATEGIES: ClassVar[Dict[EngineMode, Type[Engine]]] = {
        EngineMode.MAIN: Engine,
        EngineMode.DRY: DryEngine,
    }

    def __init__(
            self,
            workspace: Workspace,
            project_config: ProjectConfig,
            script_executor: ScriptExecutor,
            sleeper: Sleeper,
    ) -> None:
        self.workspace: Workspace = workspace
        self.project_config: ProjectConfig = project_config
        self.script_executor: ScriptExecutor = script_executor
        self.sleeper: Sleeper = sleeper
        self.llm: Optional[BaseChatModel] = self._build_llm(project_config)

    def resolve_class(self, mode: EngineMode) -> Type[Engine]:
        return self._STRATEGIES[mode]

    def create(
            self,
            mode: EngineMode,
            har_path: Path,
            http_transport: Optional[HttpTransport] = None,
    ) -> Engine:
        engine_cls: Type[Engine] = self.resolve_class(mode)
        transport: Optional[HttpTransport] = http_transport if engine_cls.USES_NETWORK else None
        if engine_cls.USES_NETWORK:
            assert transport is not None

        execution_responses_dir: Optional[Path] = (
            self.workspace.real_responses if engine_cls.USES_NETWORK else None
        )
        token_resolver_responses_dir: Path = execution_responses_dir or self.workspace.original_responses
        session_store: SessionStore = SessionStore()
        extractor_runner: ExtractorRunner = ExtractorRunner(self.workspace, self.script_executor)
        metadata_store: ExtractorMetadataStore = ExtractorMetadataStore(self.workspace)
        discovery_corpus: ResponseCorpus = ResponseCorpus(self.workspace.original_responses, Workspace.STEP_INDEX_WIDTH)
        execution_corpus: Optional[ResponseCorpus] = (
            ResponseCorpus(execution_responses_dir, Workspace.STEP_INDEX_WIDTH)
            if execution_responses_dir is not None else None
        )

        return engine_cls(
            har_path,
            self.workspace,
            session_store,
            self._build_tracker(
                discovery_corpus, execution_corpus, session_store, extractor_runner, metadata_store
            ),
            TokenResolver(token_resolver_responses_dir, session_store, extractor_runner),
            StepSkipEvaluator(self.project_config.skip_rules),
            StepRetryPolicy(),
            Validator(),
            ReplayResultComparator(self.workspace),
            self.project_config.success_criteria,
            transport,
        )

    def _build_tracker(
            self,
            discovery_corpus: ResponseCorpus,
            execution_corpus: Optional[ResponseCorpus],
            session_store: SessionStore,
            extractor_runner: ExtractorRunner,
            metadata_store: ExtractorMetadataStore,
    ) -> TokenTracker:
        agent_factory: AgentFactory = AgentFactory(self.workspace, self.script_executor, self.sleeper, self.llm)
        flow_vocabulary: FlowVocabulary = FlowVocabulary()
        candidate_resolver: CandidateResolver = CandidateResolver(
            discovery_corpus,
            OriginFinder(discovery_corpus, flow_vocabulary),
            session_store,
            extractor_runner,
            metadata_store,
            agent_factory,
            execution_corpus,
        )
        curl_token_comment: CurlTokenComment = CurlTokenComment(step_index_width=Workspace.STEP_INDEX_WIDTH)
        return TokenTracker(
            BaselineDiff(), candidate_resolver, PlaceholderApplier(session_store), CurlGenerator(curl_token_comment),
            flow_vocabulary,
        )

    @staticmethod
    def _build_llm(project_config: ProjectConfig) -> Optional[BaseChatModel]:
        if not project_config.llm:
            return None

        llm: BaseChatModel = LLMFactory.create(project_config.llm)
        print(
            f"LLM fallback enabled from config: "
            f"provider={project_config.llm.provider} model={project_config.llm.model}"
        )
        return llm
