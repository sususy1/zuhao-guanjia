from typing import Dict, Optional, Type
from .base import BasePlatformAdapter

PLATFORM_REGISTRY: Dict[str, dict] = {}


def register_platform(key, name, icon, description, adapter=None):
    PLATFORM_REGISTRY[key] = {"name": name, "icon": icon, "description": description, "adapter": adapter}


def get_platform_adapter(key) -> Optional[BasePlatformAdapter]:
    info = PLATFORM_REGISTRY.get(key)
    if not info or not info.get("adapter"):
        return None
    return info["adapter"]()


from .uhaozu import UHaoZuAdapter
from .mima import MiMaAdapter
from .xubei import XuBeiAdapter
register_platform("uhaozu", "U号租", "🔑", "U号租平台自动上下架", UHaoZuAdapter)
register_platform("zuhaowan", "租号玩", "🎮", "租号玩平台（待适配）", None)
register_platform("zuhaowang", "租号王", "👑", "租号王平台（待适配）", None)
register_platform("xubei", "虚贝", "🐚", "虚贝平台自动上下架", XuBeiAdapter)
register_platform("zhuanzhuan", "转转", "🔄", "转转平台（待适配）", None)
register_platform("mima", "密马", "🐴", "密马平台自动上下架", MiMaAdapter)
register_platform("zuhaobang", "租号帮", "🤝", "租号帮平台（待适配）", None)
