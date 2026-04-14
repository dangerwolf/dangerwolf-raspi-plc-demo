import asyncio
import threading
import logging
from datetime import datetime
from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusException
from sanic import Sanic, response

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
app = Sanic("PLC_Monitor")

config = {"plc_ip": "192.168.1.112", "plc_port": 502, "unit_id": 1, "poll_interval": 2.0, "timeout": 3.0}
data_store = {
    "connected": False, "last_update": None, "error": None,
    "alarms": {100: 0, 101: 0, 102: 0},
    "meters": {}, "rfid": {300: 0, 301: 0, 302: 0, 303: 0},
    "controls": {400: 0, 401: 0, 410: 0},
    "channels": {}, "feedback": {500: 0, 501: 0, 510: 0},
    "gas": {600: 0, 610: 0, 620: 0}
}
lock = threading.Lock()
stop_event = asyncio.Event()
poll_task = None
client = None

async def modbus_worker():
    global client
    while not stop_event.is_set():
        try:
            if client is None or not client.connected:
                client = ModbusTcpClient(config["plc_ip"], port=config["plc_port"], timeout=config["timeout"])
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, client.connect)

            def sync_read():
                with lock:
                    data_store["connected"] = True
                    data_store["error"] = None
                    r = client.read_holding_registers(100, 3, unit_id=config["unit_id"])
                    if not r.isError():
                        for i, a in enumerate([100, 101, 102]): data_store["alarms"][a] = r.registers[i]
                    r = client.read_holding_registers(200, 10, unit_id=config["unit_id"])
                    if not r.isError():
                        for i in range(10): data_store["meters"][200 + i] = r.registers[i]
                    r = client.read_holding_registers(300, 4, unit_id=config["unit_id"])
                    if not r.isError():
                        for i, a in enumerate([300, 301, 302, 303]): data_store["rfid"][a] = r.registers[i]
                    r = client.read_holding_registers(420, 6, unit_id=config["unit_id"])
                    if not r.isError():
                        for i in range(6): data_store["channels"][420 + i] = r.registers[i]
                    r = client.read_holding_registers(500, 2, unit_id=config["unit_id"])
                    if not r.isError():
                        data_store["feedback"][500] = r.registers[0]
                        data_store["feedback"][501] = r.registers[1]
                    r = client.read_holding_registers(510, 1, unit_id=config["unit_id"])
                    if not r.isError():
                        data_store["feedback"][510] = r.registers[0]
                    for a in [600, 610, 620]:
                        r = client.read_holding_registers(a, 1, unit_id=config["unit_id"])
                        if not r.isError(): data_store["gas"][a] = r.registers[0]
                    data_store["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, sync_read)

        except ModbusException as e:
            with lock:
                data_store["connected"] = False
                data_store["error"] = str(e)
            if client: client.close(); client = None
        except Exception as e:
            with lock:
                data_store["connected"] = False
                data_store["error"] = str(e)
            if client: client.close(); client = None
        await asyncio.sleep(config["poll_interval"])

@app.listener("before_server_start")
async def start_poll(app, loop):
    global poll_task, stop_event
    stop_event.clear()
    poll_task = asyncio.create_task(modbus_worker())

@app.listener("after_server_stop")
async def stop_poll(app, loop):
    global poll_task, stop_event
    stop_event.set()
    if poll_task: poll_task.cancel()
    if client: client.close()

@app.route("/")
async def index(request):
    return response.html(HTML_TEMPLATE)

@app.route("/api/data")
async def get_data(request):
    with lock:
        return response.json(data_store)

@app.route("/api/config", methods=["POST"])
async def set_config(request):
    global poll_task, stop_event
    config.update(request.json)
    stop_event.set()
    if poll_task: poll_task.cancel()
    await asyncio.sleep(0.1)
    stop_event.clear()
    poll_task = asyncio.create_task(modbus_worker())
    return response.json({"status": "ok"})

@app.route("/api/write", methods=["POST"])
async def write_register(request):
    data = request.json
    addr = data.get("address")
    val = data.get("value")
    if addr is None or val is None:
        return response.json({"error": "Missing params"}, status=400)
    try:
        if client is None or not client.connected:
            return response.json({"error": "Not connected"}, status=503)
        loop = asyncio.get_running_loop()
        res = await loop.run_in_executor(None, client.write_register, addr, val, config["unit_id"])
        if res.isError():
            return response.json({"error": "Write failed"}, status=500)
        return response.json({"status": "ok"})
    except Exception as e:
        return response.json({"error": str(e)}, status=500)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PLC 监控面板</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&display=swap" rel="stylesheet">
    <style>
        body { font-family: 'Inter', sans-serif; }
        .toggle-checkbox:checked { right: 0; border-color: #10B981; }
        .toggle-checkbox:checked + .toggle-label { background-color: #10B981; }
        .status-dot { animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: .5; } }
        .card-hover { transition: all 0.3s ease; }
        .card-hover:hover { transform: translateY(-2px); box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.1); }
    </style>
</head>
<body class="bg-gray-50 min-h-screen">
    <nav class="bg-white shadow-sm border-b border-gray-200">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div class="flex justify-between h-16">
                <div class="flex items-center">
                    <h1 class="text-xl font-bold text-gray-900">🏭 PLC 监控系统</h1>
                    <span id="connectionStatus" class="ml-4 px-3 py-1 rounded-full text-sm font-medium bg-gray-100 text-gray-600">未连接</span>
                </div>
                <div class="flex items-center space-x-4">
                    <button onclick="openSettings()" class="text-gray-600 hover:text-gray-900 px-3 py-2 rounded-md text-sm font-medium">⚙️ 设置</button>
                    <span id="lastUpdate" class="text-sm text-gray-500">--:--:--</span>
                </div>
            </div>
        </div>
    </nav>
    <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div class="mb-6">
            <h2 class="text-lg font-semibold text-gray-900 mb-4">⚠️ 报警状态</h2>
            <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div class="bg-white rounded-lg shadow p-4 card-hover border-l-4 border-red-500">
                    <div class="flex items-center justify-between"><div><p class="text-sm font-medium text-gray-600">气瓶间泄露报警</p><p class="text-2xl font-bold text-gray-900 mt-1" id="alarm100">0</p></div><div class="h-3 w-3 rounded-full bg-red-500 status-dot" id="dot100" style="display:none"></div></div>
                </div>
                <div class="bg-white rounded-lg shadow p-4 card-hover border-l-4 border-orange-500">
                    <div class="flex items-center justify-between"><div><p class="text-sm font-medium text-gray-600">厨房泄露报警</p><p class="text-2xl font-bold text-gray-900 mt-1" id="alarm101">0</p></div><div class="h-3 w-3 rounded-full bg-orange-500 status-dot" id="dot101" style="display:none"></div></div>
                </div>
                <div class="bg-white rounded-lg shadow p-4 card-hover border-l-4 border-yellow-500">
                    <div class="flex items-center justify-between"><div><p class="text-sm font-medium text-gray-600">烟感报警</p><p class="text-2xl font-bold text-gray-900 mt-1" id="alarm102">0</p></div><div class="h-3 w-3 rounded-full bg-yellow-500 status-dot" id="dot102" style="display:none"></div></div>
                </div>
            </div>
        </div>
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div class="bg-white rounded-lg shadow">
                <div class="px-4 py-5 border-b border-gray-200 sm:px-6"><h3 class="text-lg leading-6 font-medium text-gray-900">📊 仪表数值</h3></div>
                <div class="px-4 py-5 sm:p-6"><div class="grid grid-cols-2 gap-4" id="metersGrid"></div></div>
            </div>
            <div class="bg-white rounded-lg shadow">
                <div class="px-4 py-5 border-b border-gray-200 sm:px-6"><h3 class="text-lg leading-6 font-medium text-gray-900">🏷️ RFID 标签</h3></div>
                <div class="px-4 py-5 sm:p-6">
                    <div class="bg-gray-50 rounded-lg p-4">
                        <p class="text-sm text-gray-600 mb-2">完整标签号</p>
                        <p class="text-3xl font-mono font-bold text-indigo-600" id="rfidFull">00000000000000</p>
                        <div class="mt-4 grid grid-cols-4 gap-2 text-center">
                            <div class="bg-white p-2 rounded"><p class="text-xs text-gray-500">300</p><p class="font-mono font-semibold" id="rfid300">00</p></div>
                            <div class="bg-white p-2 rounded"><p class="text-xs text-gray-500">301</p><p class="font-mono font-semibold" id="rfid301">0000</p></div>
                            <div class="bg-white p-2 rounded"><p class="text-xs text-gray-500">302</p><p class="font-mono font-semibold" id="rfid302">0000</p></div>
                            <div class="bg-white p-2 rounded"><p class="text-xs text-gray-500">303</p><p class="font-mono font-semibold" id="rfid303">0000</p></div>
                        </div>
                    </div>
                </div>
            </div>
            <div class="bg-white rounded-lg shadow">
                <div class="px-4 py-5 border-b border-gray-200 sm:px-6"><h3 class="text-lg leading-6 font-medium text-gray-900">🎛️ 控制开关</h3></div>
                <div class="px-4 py-5 sm:p-6 space-y-4">
                    <div class="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
                        <div><p class="font-medium text-gray-900">厨房切断阀 (400)</p><p class="text-sm text-gray-500">反馈: <span id="feedback500">0</span></p></div>
                        <div class="relative inline-block w-12 mr-2 align-middle select-none"><input type="checkbox" id="toggle400" class="toggle-checkbox absolute block w-6 h-6 rounded-full bg-white border-4 appearance-none cursor-pointer transition-all duration-300" onchange="toggleControl(400)"/><label for="toggle400" class="toggle-label block overflow-hidden h-6 rounded-full bg-gray-300 cursor-pointer transition-colors duration-300"></label></div>
                    </div>
                    <div class="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
                        <div><p class="font-medium text-gray-900">气瓶间切断阀 (401)</p><p class="text-sm text-gray-500">反馈: <span id="feedback501">0</span></p></div>
                        <div class="relative inline-block w-12 mr-2 align-middle select-none"><input type="checkbox" id="toggle401" class="toggle-checkbox absolute block w-6 h-6 rounded-full bg-white border-4 appearance-none cursor-pointer transition-all duration-300" onchange="toggleControl(401)"/><label for="toggle401" class="toggle-label block overflow-hidden h-6 rounded-full bg-gray-300 cursor-pointer transition-colors duration-300"></label></div>
                    </div>
                    <div class="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
                        <div><p class="font-medium text-gray-900">风机 (410)</p><p class="text-sm text-gray-500">反馈: <span id="feedback510">0</span></p></div>
                        <div class="relative inline-block w-12 mr-2 align-middle select-none"><input type="checkbox" id="toggle410" class="toggle-checkbox absolute block w-6 h-6 rounded-full bg-white border-4 appearance-none cursor-pointer transition-all duration-300" onchange="toggleControl(410)"/><label for="toggle410" class="toggle-label block overflow-hidden h-6 rounded-full bg-gray-300 cursor-pointer transition-colors duration-300"></label></div>
                    </div>
                </div>
            </div>
            <div class="bg-white rounded-lg shadow">
                <div class="px-4 py-5 border-b border-gray-200 sm:px-6"><h3 class="text-lg leading-6 font-medium text-gray-900">通道状态 (420-425)</h3></div>
                <div class="px-4 py-5 sm:p-6"><div class="grid grid-cols-3 gap-3" id="channelsGrid"></div></div>
            </div>
        </div>
        <div class="mt-6 bg-white rounded-lg shadow">
            <div class="px-4 py-5 border-b border-gray-200 sm:px-6"><h3 class="text-lg leading-6 font-medium text-gray-900">🔥 可燃气体报警数值</h3></div>
            <div class="px-4 py-5 sm:p-6">
                <div class="grid grid-cols-3 gap-4">
                    <div class="text-center p-4 bg-blue-50 rounded-lg"><p class="text-sm text-blue-600 font-medium">传感器 1 (600)</p><p class="text-3xl font-bold text-blue-900 mt-2" id="gas600">0</p></div>
                    <div class="text-center p-4 bg-blue-50 rounded-lg"><p class="text-sm text-blue-600 font-medium">传感器 2 (610)</p><p class="text-3xl font-bold text-blue-900 mt-2" id="gas610">0</p></div>
                    <div class="text-center p-4 bg-blue-50 rounded-lg"><p class="text-sm text-blue-600 font-medium">传感器 3 (620)</p><p class="text-3xl font-bold text-blue-900 mt-2" id="gas620">0</p></div>
                </div>
            </div>
        </div>
    </main>
    <div id="settingsModal" class="hidden fixed inset-0 bg-gray-600 bg-opacity-50 overflow-y-auto h-full w-full z-50">
        <div class="relative top-20 mx-auto p-5 border w-96 shadow-lg rounded-md bg-white">
            <div class="mt-3">
                <h3 class="text-lg leading-6 font-medium text-gray-900 mb-4">PLC 连接设置</h3>
                <div class="space-y-4">
                    <div><label class="block text-sm font-medium text-gray-700">PLC IP 地址</label><input type="text" id="settingIp" value="192.168.30.12" class="mt-1 block w-full border border-gray-300 rounded-md shadow-sm py-2 px-3"></div>
                    <div><label class="block text-sm font-medium text-gray-700">端口</label><input type="number" id="settingPort" value="502" class="mt-1 block w-full border border-gray-300 rounded-md shadow-sm py-2 px-3"></div>
                    <div><label class="block text-sm font-medium text-gray-700">轮询间隔 (秒)</label><input type="number" id="settingInterval" value="2" step="0.5" class="mt-1 block w-full border border-gray-300 rounded-md shadow-sm py-2 px-3"></div>
                </div>
                <div class="mt-6 flex justify-end space-x-3">
                    <button onclick="closeSettings()" class="px-4 py-2 bg-gray-200 text-gray-800 rounded-md hover:bg-gray-300">取消</button>
                    <button onclick="saveSettings()" class="px-4 py-2 bg-indigo-600 text-white rounded-md hover:bg-indigo-700">保存并重启</button>
                </div>
            </div>
        </div>
    </div>
    <script>
        let updateInterval;
        function openSettings() { document.getElementById('settingsModal').classList.remove('hidden'); }
        function closeSettings() { document.getElementById('settingsModal').classList.add('hidden'); }
        async function saveSettings() {
            const config = { plc_ip: document.getElementById('settingIp').value, plc_port: parseInt(document.getElementById('settingPort').value), poll_interval: parseFloat(document.getElementById('settingInterval').value) };
            try { const res = await fetch('/api/config', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(config) }); if (res.ok) { closeSettings(); location.reload(); } } catch (e) { alert('保存设置失败: ' + e); }
        }
        async function toggleControl(addr) {
            const value = document.getElementById('toggle' + addr).checked ? 1 : 0;
            try { const res = await fetch('/api/write', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({address: addr, value: value}) }); if (!res.ok) { document.getElementById('toggle' + addr).checked = !document.getElementById('toggle' + addr).checked; alert('写入失败'); } } catch (e) { document.getElementById('toggle' + addr).checked = !document.getElementById('toggle' + addr).checked; alert('通讯错误: ' + e); }
        }
        function updateUI(data) {
            const statusEl = document.getElementById('connectionStatus');
            statusEl.className = data.connected ? 'ml-4 px-3 py-1 rounded-full text-sm font-medium bg-green-100 text-green-800' : 'ml-4 px-3 py-1 rounded-full text-sm font-medium bg-red-100 text-red-800';
            statusEl.textContent = data.connected ? '● 已连接' : '● 断开';
            document.getElementById('lastUpdate').textContent = data.last_update || '--:--:--';
            for (let addr of [100, 101, 102]) { const val = data.alarms[addr] || 0; document.getElementById('alarm' + addr).textContent = val; document.getElementById('dot' + addr).style.display = val >= 10 ? 'block' : 'none'; }
            const metersGrid = document.getElementById('metersGrid'); metersGrid.innerHTML = '';
            for (let addr in data.meters) { const div = document.createElement('div'); div.className = 'flex justify-between items-center p-2 bg-gray-50 rounded'; div.innerHTML = `<span class="text-sm text-gray-600">${addr}</span><span class="font-mono font-semibold">${data.meters[addr]}</span>`; metersGrid.appendChild(div); }
            const rfidStr = String(data.rfid[300] || 0).padStart(2, '0') + String(data.rfid[301] || 0).padStart(4, '0') + String(data.rfid[302] || 0).padStart(4, '0') + String(data.rfid[303] || 0).padStart(4, '0');
            document.getElementById('rfidFull').textContent = rfidStr;
            document.getElementById('rfid300').textContent = String(data.rfid[300] || 0).padStart(2, '0');
            document.getElementById('rfid301').textContent = String(data.rfid[301] || 0).padStart(4, '0');
            document.getElementById('rfid302').textContent = String(data.rfid[302] || 0).padStart(4, '0');
            document.getElementById('rfid303').textContent = String(data.rfid[303] || 0).padStart(4, '0');
            for (let addr of [400, 401, 410]) { document.getElementById('toggle' + addr).checked = (data.controls[addr] || 0) === 1; }
            const channelsGrid = document.getElementById('channelsGrid'); channelsGrid.innerHTML = '';
            for (let addr = 420; addr <= 425; addr++) { const val = data.channels[addr] || 0; const div = document.createElement('div'); div.className = 'flex items-center justify-between p-2 bg-gray-50 rounded'; div.innerHTML = `<span class="text-sm font-medium">通道${addr-420}</span><span class="px-2 py-1 rounded text-xs ${val ? 'bg-green-100 text-green-800' : 'bg-gray-200 text-gray-600'}">${val ? '开' : '关'}</span>`; channelsGrid.appendChild(div); }
            document.getElementById('feedback500').textContent = data.feedback[500] || 0;
            document.getElementById('feedback501').textContent = data.feedback[501] || 0;
            document.getElementById('feedback510').textContent = data.feedback[510] || 0;
            for (let addr of [600, 610, 620]) { document.getElementById('gas' + addr).textContent = data.gas[addr] || 0; }
        }
        async function fetchData() { try { const response = await fetch('/api/data'); const data = await response.json(); updateUI(data); } catch (error) { console.error('获取数据失败:', error); } }
        fetchData(); updateInterval = setInterval(fetchData, 2000);
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
