from enum import Enum


class ProxyReadiness(str, Enum):
    NOT_READY_YET = "not_ready_yet"
    READY = "ready"
    OCCUPIED_BY_OTHER_PROCESS = "occupied_by_other_process"
