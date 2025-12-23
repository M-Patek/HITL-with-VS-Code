import pkgutil
import importlib
import os
import agents.crews as crews_package
from typing import Dict, Any
from langgraph.graph.state import CompiledStateGraph

# [VS Code Plugin] 
# 硬编码仅注册 Coding Crew，大幅简化启动逻辑
TARGET_CREWS = ["coding_crew"]

class CrewRegistry:
    """
    战队注册中心 - VS Code Engine Edition
    仅加载 Coding Crew，移除其他无关 Agent 以优化性能。
    """
    _instance = None
    _crews: Dict[str, Dict[str, Any]] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(CrewRegistry, cls).__new__(cls)
            cls._instance._discover_crews()
        return cls._instance

    def _discover_crews(self):
        print("🔍 [Registry] Initializing VS Code Engine Crews...")
        
        # 兼容性处理
        if hasattr(crews_package, "__path__"):
            package_path = crews_package.__path__
        else:
            package_path = [os.path.dirname(crews_package.__file__)]

        for _, name, is_pkg in pkgutil.iter_modules(package_path):
            # 过滤：只加载 coding_crew
            if is_pkg and name in TARGET_CREWS:
                try:
                    module_name = f"agents.crews.{name}"
                    module = importlib.import_module(module_name)
                    
                    # 获取 Graph
                    crew_graph = getattr(module, "graph", None)
                    if not crew_graph:
                        try:
                            graph_module = importlib.import_module(f"{module_name}.graph")
                            crew_graph = getattr(graph_module, "graph", None)
                        except ImportError:
                            pass

                    # 获取 Meta
                    meta = getattr(module, "META", {
                        "name": name,
                        "description": "Coding Engine",
                        "trigger_phrases": []
                    })

                    if isinstance(crew_graph, CompiledStateGraph):
                        self._crews[name] = {
                            "graph": crew_graph,
                            "meta": meta,
                            "module": module
                        }
                        print(f"   ✅ Engine Loaded: {name} (Ready for VS Code)")
                    
                except Exception as e:
                    print(f"   ❌ Failed to load {name}: {e}")
        
        print("   🏁 Registry Initialization Complete.")

    def get_all_crews(self) -> Dict[str, Dict[str, Any]]:
        return self._crews

    def get_crew_graph(self, name: str) -> CompiledStateGraph:
        return self._crews.get(name, {}).get("graph")

crew_registry = CrewRegistry()
