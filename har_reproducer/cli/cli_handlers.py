import shutil
from argparse import Namespace
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Set, Type

from pydantic import TypeAdapter

from har_reproducer.config import ProjectConfigLoader
from har_reproducer.engines import Engine, EngineFactory, EngineMode
from har_reproducer.fs_io import HARParser, Workspace
from har_reproducer.models import ProjectConfig, SuccessCriterion
from har_reproducer.optimization import ReplayOptimizer
from har_reproducer.replay.curl_dependency_parser import CurlDependencyParser
from har_reproducer.replay.replay_result_comparator import ReplayResultComparator
from har_reproducer.replay.replay_runner import ReplayRunner
from har_reproducer.replay.replay_token_resolver import ReplayTokenResolver
from har_reproducer.reproduction import (
    CurlHttpTransport,
    ExtractorMetadataStore,
    ExtractorRunner,
    MitmProxyOrchestrator,
    ScriptExecutor,
    SilentExtractorMetadataStore,
    Sleeper,
    StepRetryPolicy,
)
from har_reproducer.session.session_store import SessionStore


class CliHandlers:

    def __init__(
            self,
            engine_factory: Type[EngineFactory],
            har_parser: Type[HARParser],
    ) -> None:
        self._engine_factory: Type[EngineFactory] = engine_factory
        self._har_parser: Type[HARParser] = har_parser

    def handle_run(self, args: Namespace) -> None:
        har_path: Path = Path(args.har)
        output_dir: Path = self._resolve_output_dir(args, har_path)
        if args.reset_output_dir:
            self._reset_output_dir(output_dir)
        workspace: Workspace = Workspace(output_dir)

        config_path: Optional[Path] = Path(args.config) if args.config else None
        project_config: ProjectConfig = ProjectConfigLoader.load(config_path)
        script_executor: ScriptExecutor = ScriptExecutor()
        sleeper: Sleeper = Sleeper()
        engine_factory: EngineFactory = self._engine_factory(workspace, project_config, script_executor, sleeper)

        mode: EngineMode = EngineMode(args.mode)
        result: bool = self._run(engine_factory, mode, har_path, workspace, project_config, sleeper)
        self._print_result(result)

    def _run(
            self,
            engine_factory: EngineFactory,
            mode: EngineMode,
            har_path: Path,
            workspace: Workspace,
            project_config: ProjectConfig,
            sleeper: Sleeper,
    ) -> bool:
        engine_cls: Type[Engine] = engine_factory.resolve_class(mode)
        if not engine_cls.USES_NETWORK:
            return self._run_without_proxy(engine_factory, mode, har_path)
        return self._run_with_proxy(engine_factory, mode, har_path, workspace, project_config, sleeper)

    def _run_without_proxy(self, engine_factory: EngineFactory, mode: EngineMode, har_path: Path) -> bool:
        engine: Engine = engine_factory.create(mode, har_path)
        return engine.run()

    def _run_with_proxy(
            self,
            engine_factory: EngineFactory,
            mode: EngineMode,
            har_path: Path,
            workspace: Workspace,
            project_config: ProjectConfig,
            sleeper: Sleeper,
    ) -> bool:
        orchestrator: MitmProxyOrchestrator = MitmProxyOrchestrator(
            workspace,
            project_config.proxy_port,
            project_config.ca_cert_path
        )
        http_transport: CurlHttpTransport = CurlHttpTransport(
            workspace, orchestrator.port, orchestrator.ca_cert_path, sleeper
        )
        engine: Engine = engine_factory.create(mode, har_path, http_transport=http_transport)
        return orchestrator.run(engine.run)

    @staticmethod
    def _print_result(result: bool) -> None:
        if result:
            print("\nReproduction SUCCESSFUL: Target state reached.")
        else:
            print("\nReproduction FAILED: Target state not reached.")

    def handle_parse(self, args: Namespace) -> None:
        har_path: Path = Path(args.har)
        output_dir: Path = self._resolve_output_dir(args, har_path)
        if args.reset_output_dir:
            self._reset_output_dir(output_dir)
        count: int = self._har_parser.split_har(har_path, output_dir)
        print(f"Parsed HAR into {count} steps.")

    def handle_replay(self, args: Namespace) -> None:
        output_dir: Path = Path(args.output)
        self._validate_replay_mode_flags(args)
        workspace: Workspace = self._prepare_replay_workspace(output_dir)

        project_config: ProjectConfig = ProjectConfigLoader.load(Path(args.config) if args.config else None)
        res_refer_dir: Path = self._resolve_response_reference_dir(workspace, project_config)

        run_id: str = datetime.now().strftime("%Y%m%d_%H%M%S")
        orchestrator: MitmProxyOrchestrator = MitmProxyOrchestrator(
            workspace, project_config.proxy_port, project_config.ca_cert_path
        )
        script_executor: ScriptExecutor = ScriptExecutor()
        sleeper: Sleeper = Sleeper()
        runner: ReplayRunner = self._build_replay_runner(
            workspace, orchestrator, run_id, res_refer_dir, script_executor, sleeper
        )

        result: bool = orchestrator.run(lambda: self._dispatch_replay_mode(runner, args))
        self._print_result(result)

    def handle_optimize(self, args: Namespace) -> None:
        output_dir: Path = Path(args.output)
        workspace: Workspace = self._prepare_replay_workspace(output_dir)

        project_config: ProjectConfig = ProjectConfigLoader.load(Path(args.config) if args.config else None)
        success_criteria: List[SuccessCriterion] = self._resolve_optimize_success_criteria(args, project_config)
        res_refer_dir: Path = self._resolve_response_reference_dir(workspace, project_config)

        run_id: str = datetime.now().strftime("%Y%m%d_%H%M%S")
        orchestrator: MitmProxyOrchestrator = MitmProxyOrchestrator(
            workspace, project_config.proxy_port, project_config.ca_cert_path
        )
        script_executor: ScriptExecutor = ScriptExecutor()
        sleeper: Sleeper = Sleeper()
        runner: ReplayRunner = self._build_replay_runner(
            workspace, orchestrator, run_id, res_refer_dir, script_executor, sleeper,
            metadata_store_factory=SilentExtractorMetadataStore,
        )
        self._validate_optimize_from_index(runner, args.from_index)

        optimizer: ReplayOptimizer = ReplayOptimizer(
            schedule_executor=runner,
            metadata_store=SilentExtractorMetadataStore(workspace),
            max_requests=args.max_requests,
        )
        output_path: Optional[Path] = Path(args.steps_out) if args.steps_out else None

        result: Optional[List[int]] = orchestrator.run(
            lambda: optimizer.optimize(
                workspace, run_id, args.from_index, args.to_index, success_criteria, output_path
            )
        )
        self._print_optimize_result(result, output_path or workspace.optimized_steps_file(run_id))

    @staticmethod
    def _resolve_optimize_success_criteria(args: Namespace, project_config: ProjectConfig) -> List[SuccessCriterion]:
        if args.success_criteria:
            adapter: TypeAdapter[List[SuccessCriterion]] = TypeAdapter(List[SuccessCriterion])
            criteria: List[SuccessCriterion] = adapter.validate_json(args.success_criteria)
        else:
            criteria = project_config.success_criteria
        if not criteria:
            raise ValueError(
                "handle_optimize: success_criteria vazio — informe --success-criteria ou configure "
                "success_criteria no config.json antes de rodar optimize."
            )
        return criteria

    @staticmethod
    def _validate_optimize_from_index(runner: ReplayRunner, from_index: int) -> None:
        existing: Set[int] = set(runner.existing_step_indexes())
        if from_index not in existing:
            raise ValueError(
                f"ReplayOptimizer: step(s) [{from_index}] não existem no workspace (nenhum curl file em disco) — "
                f"provavelmente foram pulados por skip_rules ou estão fora do intervalo de steps existentes."
            )

    @staticmethod
    def _print_optimize_result(result: Optional[List[int]], destination: Path) -> None:
        if result is not None:
            print(f"\nOptimization SUCCESSFUL: {len(result)} step(s) written to {destination}")
        else:
            print("\nOptimization FAILED: unable to find a passing subset (see abort reason above).")

    @staticmethod
    def _prepare_replay_workspace(output_dir: Path) -> Workspace:
        if not output_dir.exists():
            raise ValueError(f"Workspace directory does not exist: {output_dir}")

        workspace: Workspace = Workspace(output_dir)
        if not any(workspace.curls.glob("req_*.curl.sh")):
            raise ValueError(f"Workspace has no curl files: {output_dir}")
        return workspace

    @staticmethod
    def _resolve_response_reference_dir(workspace: Workspace, project_config: ProjectConfig) -> Path:
        res_refer_dir: Path = project_config.response_reference_dir or workspace.real_responses
        if not res_refer_dir.exists():
            raise ValueError(f"response_reference_dir does not exist: {res_refer_dir}")
        return res_refer_dir

    @staticmethod
    def _build_replay_runner(
            workspace: Workspace,
            orchestrator: MitmProxyOrchestrator,
            run_id: str,
            res_refer_dir: Path,
            script_executor: ScriptExecutor,
            sleeper: Sleeper,
            metadata_store_factory: Type[ExtractorMetadataStore] = ExtractorMetadataStore,
    ) -> ReplayRunner:
        session_store: SessionStore = SessionStore()
        extractor_runner: ExtractorRunner = ExtractorRunner(workspace, script_executor)
        dependency_parser: CurlDependencyParser = CurlDependencyParser()
        metadata_store: ExtractorMetadataStore = metadata_store_factory(workspace)
        replay_token_resolver: ReplayTokenResolver = ReplayTokenResolver(
            session_store, extractor_runner, dependency_parser, metadata_store
        )
        retry_policy: StepRetryPolicy = StepRetryPolicy()
        comparator: ReplayResultComparator = ReplayResultComparator(workspace)
        http_transport: CurlHttpTransport = CurlHttpTransport(
            workspace, orchestrator.port, orchestrator.ca_cert_path, sleeper
        )

        return ReplayRunner(
            workspace=workspace,
            dependency_parser=dependency_parser,
            session_store=session_store,
            http_transport=http_transport,
            replay_token_resolver=replay_token_resolver,
            retry_policy=retry_policy,
            comparator=comparator,
            run_id=run_id,
            replay_run_dir=workspace.replay_run_dir(run_id),
            res_refer_dir=res_refer_dir,
            original_responses_dir=workspace.original_responses,
        )

    @staticmethod
    def _dispatch_replay_mode(runner: ReplayRunner, args: Namespace) -> bool:
        if args.mode == "all":
            return runner.run_all()
        if args.mode == "slice":
            return runner.run_slice(args.from_index, args.to_index)
        if args.mode == "smart":
            return runner.run_smart(args.from_index, args.to_index)
        return runner.run_list(Path(args.steps_file))

    @staticmethod
    def _validate_replay_mode_flags(args: Namespace) -> None:
        if args.mode == "all" and (
                args.from_index is not None or args.to_index is not None or args.steps_file is not None):
            raise ValueError("--from/--to/--steps-file não se aplicam a --mode all")
        if args.mode in ("slice", "smart"):
            if args.steps_file is not None:
                raise ValueError(f"--steps-file não se aplica a --mode {args.mode}")
            if args.from_index is not None and args.to_index is not None and args.from_index > args.to_index:
                raise ValueError("--from não pode ser maior que --to")
        if args.mode == "list":
            if args.steps_file is None:
                raise ValueError("--mode list exige --steps-file")
            if args.from_index is not None or args.to_index is not None:
                raise ValueError("--from/--to não se aplicam a --mode list")

    @staticmethod
    def _resolve_output_dir(args: Namespace, har_path: Path) -> Path:
        return Path(args.output) if args.output else har_path.parent / "output"

    @staticmethod
    def _reset_output_dir(output_dir: Path) -> None:
        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
