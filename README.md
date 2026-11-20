# Tram

可插拔的插件式 Agent 框架：**事件即链，链即洋葱；插件是带生命周期的行为参与者，模型只是链上负责"智能"的一站。**

本仓库为框架实现仓。设计文档位于 `D:\project\文档仓库\学习\Agent\Tram\`：

| 文档 | 内容 |
|---|---|
| 设计总览.md | 面向评审的整体设计与可行性（新人从这里读） |
| 术语说明.md | 回复 / 轮次 / ctx / 插件链 词表 |
| 架构说明.md | 三层架构：engine 程序层 / host 通信层 / plugin 插件层 |
| 流程控制.md | 一条回复的完整流程、申请续轮、轮次上限、缓冲送达 |
| 生命周期.md | 会话级与插件级生命周期、中断与异常语义 |
| 插件链.md | 插件装配、清单格式、方法注册、执行与门控 |
| 上下文设计.md | ctx 信封（待整理） |

本仓内另维护 `spec/` 规格知识库：从代码提炼的契约规范（事件集、插件链、操作、轮次、存储），随代码同步更新，入口见 [spec/README.md](spec/README.md)。

## 仓库结构

```
engine/   程序层：会话管理、生命周期编排、用户相关操作
host/     通信层：插件链装配与执行、消息与轮次控制、归组注册表、操作日志（隔离带）
plugins/  插件层：一切数据取自通信层，一切结果汇报给通信层
tests/    契约级测试（按新契约从零写）
spec/     规格知识库：代码契约随代码同步维护（见 spec/README.md）
```

## 一期范围

- 单实例、单链；会话内轮次串行（同一会话至多一个进行中的轮次）
- 存储：stdlib `sqlite3` 单文件，无 ORM；
- 送达：缓冲制（回复在 onReply 收尾执行完毕前不对用户展示，之后一次性送达）
- 信任模型：插件全信任（权限细分二期）

## 运行与配置

```bash
pip install openai          # llm 插件依赖（OpenAI 协议）
python main.py              # CLI；GUI 用 python -m gui.server
```

- 插件配置走插件自己的 manifest：把各插件目录下的 `manifest.example.json` 复制为 `manifest.json` 并填写 `config`（`manifest.json` 已进 .gitignore，密钥不会入库）。llm 的 `api_key` 留空时回退环境变量 `OPENAI_API_KEY` / `OPENAI_BASE_URL`
- 基础插件集：`prompt`（系统提示词）→ `llm`（OpenAI 协议对话）→ `fs`（文件工具，限定 `data/workspace/`）→ `shell`（命令执行，高危可停用）；工具协作见 [spec/tool-protocol.md](spec/tool-protocol.md)
- 首次构建自动种子：目标链序、停用演示插件 hello / byebye、`MAX_TURN_COUNT=16`

## 纪律

- 一切上下文操作经通信层，禁止直接操作存储；通信层生成操作日志（重放与回归的依据）
- 事件集封闭（会话级 7 个 + 插件级 4 个），插件不可造新事件
- ctx 上不挂自由字段：受管操作走 ctx API（入操作日志），临时状态放插件实例
