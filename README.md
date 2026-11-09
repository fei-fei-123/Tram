# Tram 宿主页

拓扑驱动 Agent 框架 **Tram** 的宿主页：**宿主层**（服务＋插件体系＋页面）内嵌**引擎层**（滤器链）。

- 引擎规范：`D:\project\文档仓库\学习\Agent\Tram\形态.md`（机制白清单四件：doFilter 递归 / 列表装配 / deps 口子 / trace 写入）
- 域模型词表：`docs/域模型.md`（新概念必须先按四栏补进文档再写代码）
- 技术栈：`docs/技术栈.md`

## 布局

```
host/     宿主层：EventBus、SQLite 存储、Session/Message/Turn 三服务、插件体系（base/context/manager）、装配根 app.py
engine/   引擎层：chain（doFilter 递归＋装配）、trace（jsonl，逐轮请求/响应）、filters/（echo｜llm）、providers（OpenAI 兼容适配器）
plugins/  插件仓（hello：三条改动路径示范）
tests/    pytest
```

命名纪律：业务说 slot，代码说 filter（docs/域模型.md「词表映射」节）。

## 阶段

- **A**：EventBus ＋ Session/Message/Turn 三服务（引擎 stub 为 echo）＋ PluginManager ＋ hello 插件，pytest 全绿。
- **B**：llm 滤器（provider 外置，作为普通成员进列表）＋ trace 升格（必记 LLM 视图＋逐轮请求/响应）。Case 1 验收：请求原样回、trace 多一行。接真模型：`build_app(data_dir, engine_config={"filters": [llm], "provider": OpenAICompatProvider(...)})`。

```
python -m pytest
```

## 接真模型

仓库根 `config.json`（build_app 缺省读取；测试固定离线不读它）：

```json
{
  "filters": ["llm"],
  "provider": { "base_url": "https://…/v1", "model": "…", "api_key": "…", "timeout": 120 }
}
```

注意 base_url 要带 `/v1`（适配器只补 `/chat/completions`）。冒烟：`python scripts\smoke_llm.py [提示词]`。若建仓，config.json 含 key，须进 .gitignore。
