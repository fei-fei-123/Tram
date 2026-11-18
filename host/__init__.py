"""通信层（host）：程序层与插件层之间的隔离带。

职责（架构说明.md / 插件链.md / 流程控制.md）：
- 插件链管理：按生命周期事件装配链（全局配置列表 × 注册表，先到先得），
  洋葱模型执行；装配期校验事件名；执行前 isOpen 门控（停用跳过且链继续）
- 异常语义：链内 Exception 一律不上抛——记日志、回程照常；前半段异常额外
  标记回复级中断原因（先到先得），收尾段经 ctx.get_interrupt() 查询；
  BaseException 留痕后原样上抛；doFilter 一次性消费，重复调用不触发下游
- 注册与装卸：resFilter(事件名, 方法) 双表登记（registry[event] / owned[plugin]）；
  卸载按归组注册表统一拆除后重算链；不向插件返回句柄
- 消息与轮次控制：拉起轮次；续轮申请在轮末统一裁决（先到先得合并为一次）；
  轮次上限管理（可配置）；回复缓冲送达
- 操作日志：一切上下文操作经本层并记录（谁 / 操作 write-add-delete-read / 对象消息 / 前后值）
  ——重放与回归测试的依据；LLM 响应由日志注入，重放指状态演化推演

事件集（封闭，不可新增）：
- 会话级：onStart / onPause / onRecover / onReply / onTurn / onArchive / onDelete
- 插件级：onLoad / onEnable / onDisable / onUnload

建议模块切分（实现时自定）：chains（装配与执行）/ registry（归组注册表）/
oplog（操作日志）/ turns（轮次控制）/ dispatch（生命周期分发）

设计依据：文档仓库 学习/Agent/Tram/ 下的 插件链.md、流程控制.md、架构说明.md
"""
