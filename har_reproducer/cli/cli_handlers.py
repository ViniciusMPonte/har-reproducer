import shutil
from argparse import Namespace
from datetime import datetime
from pathlib import Path
from typing import Optional, Type

from har_reproducer.config import ProjectConfigLoader
from har_reproducer.engines import Engine, EngineFactory, EngineMode
from har_reproducer.fs_io import HARParser, Workspace
from har_reproducer.models import ProjectConfig
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
        Workspace.init(output_dir)

        config_path: Optional[Path] = Path(args.config) if args.config else None
        project_config: ProjectConfig = ProjectConfigLoader.load(config_path)
        script_executor: ScriptExecutor = ScriptExecutor()
        sleeper: Sleeper = Sleeper()
        engine_factory: EngineFactory = self._engine_factory(project_config, script_executor, sleeper)

        mode: EngineMode = EngineMode(args.mode)
        result: bool = self._run(engine_factory, mode, har_path, project_config, sleeper)
        self._print_result(result)

    def _run(
            self,
            engine_factory: EngineFactory,
            mode: EngineMode,
            har_path: Path,
            project_config: ProjectConfig,
            sleeper: Sleeper,
    ) -> bool:
        engine_cls: Type[Engine] = engine_factory.resolve_class(mode)
        if not engine_cls.USES_NETWORK:
            return self._run_without_proxy(engine_factory, mode, har_path)
        return self._run_with_proxy(engine_factory, mode, har_path, project_config, sleeper)

    def _run_without_proxy(self, engine_factory: EngineFactory, mode: EngineMode, har_path: Path) -> bool:
        engine: Engine = engine_factory.create(mode, har_path)
        return engine.run()

    def _run_with_proxy(
            self,
            engine_factory: EngineFactory,
            mode: EngineMode,
            har_path: Path,
            project_config: ProjectConfig,
            sleeper: Sleeper,
    ) -> bool:
        orchestrator: MitmProxyOrchestrator = MitmProxyOrchestrator(
            project_config.proxy_port,
            project_config.ca_cert_path
        )
        http_transport: CurlHttpTransport = CurlHttpTransport(orchestrator.port, orchestrator.ca_cert_path, sleeper)
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
        self._prepare_replay_workspace(output_dir)

        project_config: ProjectConfig = ProjectConfigLoader.load(Path(args.config) if args.config else None)
        res_refer_dir: Path = self._resolve_response_reference_dir(project_config)

        run_id: str = datetime.now().strftime("%Y%m%d_%H%M%S")
        orchestrator: MitmProxyOrchestrator = MitmProxyOrchestrator(project_config.proxy_port,
                                                                    project_config.ca_cert_path)
        script_executor: ScriptExecutor = ScriptExecutor()
        sleeper: Sleeper = Sleeper()
        runner: ReplayRunner = self._build_replay_runner(
            orchestrator, run_id, res_refer_dir, script_executor, sleeper
        )

        result: bool = orchestrator.run(lambda: self._dispatch_replay_mode(runner, args))
        self._print_result(result)

    @staticmethod
    def _prepare_replay_workspace(output_dir: Path) -> None:
        if not output_dir.exists():
            raise ValueError(f"Workspace directory does not exist: {output_dir}")

        Workspace.init(output_dir)
        if not any(Workspace.curls.glob("req_*.curl.sh")):
            raise ValueError(f"Workspace has no curl files: {output_dir}")

    @staticmethod
    def _resolve_response_reference_dir(project_config: ProjectConfig) -> Path:
        res_refer_dir: Path = project_config.response_reference_dir or Workspace.real_responses
        if not res_refer_dir.exists():
            raise ValueError(f"response_reference_dir does not exist: {res_refer_dir}")
        return res_refer_dir

    @staticmethod
    def _build_replay_runner(
            orchestrator: MitmProxyOrchestrator,
            run_id: str,
            res_refer_dir: Path,
            script_executor: ScriptExecutor,
            sleeper: Sleeper,
    ) -> ReplayRunner:
        session_store: SessionStore = SessionStore()
        extractor_runner: ExtractorRunner = ExtractorRunner(script_executor)
        dependency_parser: CurlDependencyParser = CurlDependencyParser()
        metadata_store: ExtractorMetadataStore = ExtractorMetadataStore()
        replay_token_resolver: ReplayTokenResolver = ReplayTokenResolver(
            session_store, extractor_runner, dependency_parser, metadata_store
        )
        retry_policy: StepRetryPolicy = StepRetryPolicy()
        comparator: ReplayResultComparator = ReplayResultComparator()
        http_transport: CurlHttpTransport = CurlHttpTransport(orchestrator.port, orchestrator.ca_cert_path, sleeper)

        return ReplayRunner(
            dependency_parser=dependency_parser,
            session_store=session_store,
            http_transport=http_transport,
            replay_token_resolver=replay_token_resolver,
            retry_policy=retry_policy,
            comparator=comparator,
            run_id=run_id,
            replay_run_dir=Workspace.replay_run_dir(run_id),
            res_refer_dir=res_refer_dir,
            original_responses_dir=Workspace.original_responses,
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
