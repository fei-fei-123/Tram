# Tram

Tram是一款基于插件的智能体（Agent） 框架，用于构建可扩展的智能体系统。

主要应用场景在于垂直领域的智能体系统，如医疗、法律、金融等。

## 亮点与功能

- [x] 可插拔的插件式 Agent 框架可插拔的插件式 Agent 框架
- [x] 插件链式调用
- [x] 插件生命周期管理
- [ ] 可记录与回放操作日志
- [ ] 插件权限管理
- [ ] Agent 与 Sub-Agent
- [ ] 多实例、多链、多会话支持

## 如何使用

### 对插件进行开发与配置

插件的开发：[快速开始](docs/快速开始.md)

对于部分插件提供了默认的配置文件，使用前请先复制 `manifest.example.json` 为 `manifest.json`，并填写相关 `config`。

### 运行与配置

```bash
pip install -r requirements.txt
python main.py              # CLI；GUI 用 python -m gui.server
```

- 插件配置走插件自己的 manifest：把各插件目录下的 `manifest.example.json` 复制为 `manifest.json` 并填写 `config`（`manifest.json` 已进 .gitignore，密钥不会入库）。llm 的 `api_key` 留空时回退环境变量 `OPENAI_API_KEY` / `OPENAI_BASE_URL`
- 基础插件集：`prompt`（系统提示词）→ `llm`（OpenAI 协议对话）→ `fs`（文件工具，限定 `data/workspace/`）→ `shell`（命令执行，高危可停用） → `network`（网络工具）

## License

MIT，见 [LICENSE](LICENSE)。
