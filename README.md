

# Inovance PLC Modbus TCP 监控面板

[TOC]

## 项目背景
树莓派作为边缘采集节点，通过 Modbus TCP 协议与汇川 PLC 建立工业数据通讯链路。系统提供实时数据采集、状态可视化与远程控制功能。采用 Sanic 异步框架维持高并发请求响应效率，配合线程池执行同步 Modbus 操作。

## 项目内容
- 异步轮询引擎独立运行，持续采集 PLC 寄存器数据
- 实时 Web 面板展示报警状态、仪表数值、RFID 标签与控制开关
- 前端 Toggle 控件直连寄存器写入，支持双向状态同步
- 动态配置接口支持在线修改 PLC IP、端口与轮询周期
- 线程锁保护共享数据字典，保障并发读写一致性

## 约定通讯变量
| 地址范围 | 变量名称 | 数据类型 | 读写权限 | 数值说明 |
|---|---|---|---|---|
| 100-102 | 报警状态 | 离散量 | 只读 | 0=正常，10=报警触发 |
| 200-209 | 仪表数值 | 模拟量 | 只读 | 原始寄存器整型值 |
| 300-303 | RFID 标签 | 组合字段 | 只读 | 300(2位)+301/302/303(各4位)，前端自动补零拼接为14位 |
| 400, 401 | 切断阀控制 | 开关量 | 只写 | 0=关闭，1=打开 |
| 410 | 风机控制 | 开关量 | 只写 | 0=关闭，1=打开 |
| 420-425 | 通道状态 | 开关量 | 只读 | 0=关闭，1=打开 |
| 500, 501 | 阀门反馈 | 开关量 | 只读 | 0=关闭，1=打开 |
| 510 | 风机反馈 | 开关量 | 只读 | 0=关闭，1=打开 |
| 600, 610, 620 | 可燃气体数值 | 模拟量 | 只读 | 实时传感器读数 |

## 项目结构
```
plc_monitor/
├── app.py              # Sanic 主程序、路由定义、Modbus 轮询逻辑、前端模板
├── requirements.txt    # Python 依赖清单
└── README.md           # 项目说明文档
```

## 部署要求
运行环境需满足 Python 3.9 及以上版本。树莓派系统保持与 PLC 同一局域网段。防火墙放行 502 (Modbus) 与 5000 (Web) 端口。

安装依赖：
```bash
pip install sanic>=23.0.0 pymodbus>=3.6.0
```

启动服务：
```bash
python3 app.py
```

访问地址：`http://<树莓派IP>:5000`

配置参数通过 `/api/config` 接口动态加载。Modbus 客户端使用 `asyncio.get_running_loop().run_in_executor` 移交同步请求至线程池。数据字典通过 `threading.Lock` 保护并发读写。轮询间隔默认 2 秒，支持前端页面实时调整。

## 运行截图
[]{https://raw.githubusercontent.com/dangerwolf/dangerwolf-raspi-plc-demo/refs/heads/main/Screenshot/iShot_2026-04-14_18.02.17.png}
[]{https://raw.githubusercontent.com/dangerwolf/dangerwolf-raspi-plc-demo/refs/heads/main/Screenshot/iShot_2026-04-14_18.02.28.png}

执行启动命令后访问 Web 地址进入监控面板。确认 PLC 寄存器基址为 0。部署前验证树莓派与 PLC 网络连通性。
