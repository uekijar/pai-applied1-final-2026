import os
import re
import json
import requests
import subprocess
import threading
import time
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import rclpy
from rclpy.node import Node
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint
from tf2_ros import Buffer, TransformListener
import uvicorn

app = FastAPI()
ros_node = None

# ==========================================
# 設定 (LLMとMarkdown)
# ==========================================
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "qwen2.5-coder:7b" 

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MARKDOWN_PATH = os.path.join(BASE_DIR, "patients.md")

# ==========================================
# Web UI (HTML/CSS/JS)
# ==========================================
html_content = """
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <title>AI配薬アシスタント</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f0f2f5; margin: 0; padding: 20px; display: flex; flex-direction: column; height: 90vh; }
        .header { background: #0056b3; color: white; padding: 15px; border-radius: 8px 8px 0 0; font-weight: bold; font-size: 1.2em; display: flex; justify-content: space-between; align-items: center;}
        .chat-container { background: white; flex-grow: 1; padding: 20px; overflow-y: auto; border-left: 1px solid #ccc; border-right: 1px solid #ccc; display: flex; flex-direction: column; gap: 15px;}
        .input-area { background: #e9ecef; padding: 15px; border-radius: 0 0 8px 8px; border: 1px solid #ccc; display: flex; gap: 10px; }
        input[type="text"] { flex-grow: 1; padding: 12px; border: 1px solid #ccc; border-radius: 5px; font-size: 16px; }
        button { padding: 12px 20px; border: none; border-radius: 5px; cursor: pointer; background: #28a745; color: white; font-weight: bold; font-size: 16px; transition: 0.2s; }
        button:hover { background: #218838; }
        .btn-reset { background: #dc3545; }
        .btn-reset:hover { background: #c82333; }
        .msg { display: flex; flex-direction: column; }
        .msg.user { align-items: flex-end; }
        .msg.sys { align-items: flex-start; }
        .bubble { max-width: 75%; padding: 12px 18px; border-radius: 15px; line-height: 1.5; box-shadow: 0 1px 2px rgba(0,0,0,0.1); }
        .msg.user .bubble { background: #007bff; color: white; border-bottom-right-radius: 2px; }
        .msg.sys .bubble { background: #f1f0f0; color: #333; border-bottom-left-radius: 2px; }
        .loading { font-style: italic; color: #666; }
    </style>
</head>
<body>
    <div class="header">
        <span>🤖 AI配薬アシスタント (Local LLM RAG)</span>
        <button class="btn-reset" onclick="resetArm()">🔄 アーム初期化</button>
    </div>
    <div class="chat-container" id="chat">
        <div class="msg sys"><div class="bubble">処方箋知識ベースを読み込みました。<br>配薬の指示を自然言語で入力してください。（例：「Aさんの朝の薬をお願い」）</div></div>
    </div>
    <div class="input-area">
        <input type="text" id="userInput" placeholder="指示を入力..." onkeypress="if(event.key === 'Enter') sendMessage()">
        <button onclick="sendMessage()">送信 🚀</button>
    </div>

    <script>
        const chat = document.getElementById('chat');
        const userInput = document.getElementById('userInput');

        function addMessage(text, sender, isHtml=false) {
            const msgDiv = document.createElement('div');
            msgDiv.className = `msg ${sender}`;
            msgDiv.innerHTML = `<div class="bubble">${isHtml ? text : text.replace(/\\n/g, '<br>')}</div>`;
            chat.appendChild(msgDiv);
            chat.scrollTop = chat.scrollHeight;
            return msgDiv;
        }

        async function sendMessage() {
            const text = userInput.value.trim();
            if (!text) return;
            
            addMessage(text, 'user');
            userInput.value = '';
            
            // ローディング表示
            const loadingMsg = addMessage('<span class="loading">⏳ LLM推論中...</span>', 'sys', true);

            try {
                const response = await fetch('/chat_infer', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ prompt: text })
                });
                const data = await response.json();
                
                // ローディング消去して結果表示
                chat.removeChild(loadingMsg);
                addMessage(data.reply, 'sys');
                
            } catch (err) {
                chat.removeChild(loadingMsg);
                addMessage('⚠️ 通信エラーが発生しました。', 'sys');
            }
        }

        async function resetArm() {
            addMessage('アームを初期位置に戻します...', 'sys');
            await fetch('/execute_action', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ patient: 'none', time: 'none', target_drug: 'reset' })
            });
        }
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def serve_ui():
    return html_content

# ==========================================
# APIエンドポイント (推論と制御)
# ==========================================
class ChatRequest(BaseModel):
    prompt: str

class ActionRequest(BaseModel):
    patient: str
    time: str
    target_drug: str

@app.post("/chat_infer")
def chat_infer(req: ChatRequest):
    """ブラウザからの入力を受け取り、LLM推論を経てアームを動かす統合エンドポイント"""
    try:
        with open(MARKDOWN_PATH, "r", encoding="utf-8") as f:
            context = f.read()
    except FileNotFoundError:
        return {"reply": "⚠️ エラー: patients.md が見つかりません。"}

    llm_prompt = f"""
あなたは病院の配薬アシスタントAIです。
以下の処方箋データ(Markdown)を参照し、ユーザーの指示から患者名、時間帯、該当する薬のシステムIDを特定してください。
回答は必ず以下のJSON形式のみを出力し、他のテキストは一切含めないでください。

【処方箋データ】
{context}

【ユーザー指示】
{req.prompt}

【出力形式】
{{
  "patient": "抽出した患者名",
  "time": "抽出した時間帯",
  "target_drug": "該当するシステムID(red_medicineなど)"
}}
"""
    try:
        # ローカルLLM (Ollama) へリクエスト
        res = requests.post(OLLAMA_URL, json={
            "model": MODEL_NAME, "prompt": llm_prompt, "stream": False, "format": "json"
        })
        res.raise_for_status()
        result_text = res.json().get("response", "")
        
        json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
        if json_match:
            action_data = json.loads(json_match.group(0))
            ext_patient = action_data.get("patient", "不明")
            ext_time = action_data.get("time", "不明")
            target_drug = action_data.get("target_drug", "none")
            
            if target_drug in ["red_medicine", "blue_medicine"]:
                # ROS 2 アームへ動作指示 (別スレッド)
                if ros_node:
                    threading.Thread(target=ros_node.execute_pick_and_place, args=(target_drug,), daemon=True).start()
                return {"reply": f"✅ 推論成功: {ext_patient}の{ext_time}の薬（{target_drug}）を特定しました。\nロボットアームで準備を開始します！"}
            else:
                return {"reply": "⚠️ 該当する薬が処方データに見つかりませんでした。"}
        else:
            return {"reply": "⚠️ LLMの出力から情報を抽出できませんでした。"}
            
    except Exception as e:
        return {"reply": f"⚠️ LLM推論中にエラーが発生しました: {str(e)}"}

@app.post("/execute_action")
def execute_action(req: ActionRequest):
    """リセットボタン等から直接アームを制御するためのエンドポイント"""
    if ros_node:
        if req.target_drug == "reset":
            subprocess.Popen(["python3", "/ros2_ws/src/spawn_objects.py"])
        else:
            threading.Thread(target=ros_node.execute_pick_and_place, args=(req.target_drug,), daemon=True).start()
        return {"status": "success"}
    return {"status": "error"}

# ==========================================
# 以下、ROS 2 ロボット制御ロジック (変更なし)
# ==========================================
def create_bottle_sdf(name, r, g, b):
    return f"""<?xml version="1.0" ?><sdf version="1.6"><model name="{name}"><static>true</static><link name="link"><visual name="body"><pose>0 0 0.04 0 0 0</pose><geometry><cylinder><radius>0.025</radius><length>0.08</length></cylinder></geometry><material><ambient>{r} {g} {b} 1</ambient><diffuse>{r} {g} {b} 1</diffuse></material></visual><visual name="cap"><pose>0 0 0.085 0 0 0</pose><geometry><cylinder><radius>0.018</radius><length>0.015</length></cylinder></geometry><material><ambient>0.95 0.95 0.95 1</ambient><diffuse>0.95 0.95 0.95 1</diffuse></material></visual></link></model></sdf>"""

indicator_sdf = """<?xml version="1.0" ?><sdf version="1.6"><model name="grip_indicator"><static>true</static><link name="link"><visual name="light"><geometry><sphere><radius>0.035</radius></sphere></geometry><material><ambient>1 0.8 0 0.8</ambient><diffuse>1 0.8 0 0.8</diffuse></material></visual></link></model></sdf>"""

def delete_entity(name):
    subprocess.run(["ros2", "service", "call", "/delete_entity", "gazebo_msgs/srv/DeleteEntity", f"{{name: '{name}'}}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def spawn_entity(name, xml_content, x, y, z):
    delete_entity(name)
    filename = f"/tmp/{name}.sdf"
    with open(filename, "w") as f: f.write(xml_content)
    subprocess.run(["ros2", "run", "gazebo_ros", "spawn_entity.py", "-entity", name, "-file", filename, "-x", str(x), "-y", str(y), "-z", str(z)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

class ArmControllerNode(Node):
    def __init__(self):
        super().__init__('arm_controller_bridge')
        self.publisher = self.create_publisher(JointTrajectory, '/joint_trajectory_controller/joint_trajectory', 10)
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

    def get_current_tool_xy(self):
        for frame in ['world', 'base_link', 'base']:
            try:
                trans = self.tf_buffer.lookup_transform(frame, 'tool0', rclpy.time.Time())
                return trans.transform.translation.x, trans.transform.translation.y, trans.transform.translation.z
            except Exception:
                continue
        return 0.0, 0.0, 0.1

    def publish_joint_positions(self, positions, duration_sec):
        msg = JointTrajectory()
        msg.joint_names = ['shoulder_pan_joint', 'shoulder_lift_joint', 'elbow_joint', 'wrist_1_joint', 'wrist_2_joint', 'wrist_3_joint']
        point = JointTrajectoryPoint()
        point.positions = [float(p) for p in positions]
        point.time_from_start.sec = int(duration_sec)
        msg.points.append(point)
        self.publisher.publish(msg)

    def execute_pick_and_place(self, target_drug):
        if target_drug == "red_medicine":
            pan_pick, obj_name, color, place_pan = -0.7, "red_medicine_obj", (0.9, 0.1, 0.1), -0.12
        elif target_drug == "blue_medicine":
            pan_pick, obj_name, color, place_pan = 0.5, "blue_medicine_obj", (0.1, 0.3, 0.9), 0.12
        else:
            return

        hover_joints = [pan_pick, -1.1, 1.3, -1.77, -1.57, 0.0]
        pick_joints  = [pan_pick, -1.25, 1.65, -1.97, -1.57, 0.0]
        tray_hover_joints = [place_pan, -1.1, 1.3, -1.77, -1.57, 0.0]
        tray_place_joints = [place_pan, -1.23, 1.62, -1.96, -1.57, 0.0]
        home_joints       = [0.0, -1.57, 0.0, -1.57, 0.0, 0.0]

        self.publish_joint_positions(hover_joints, 2)
        time.sleep(2.2)
        self.publish_joint_positions(pick_joints, 2)
        time.sleep(2.2)

        gx, gy, gz = self.get_current_tool_xy()
        spawn_entity("grip_indicator", indicator_sdf, gx, gy, gz)
        delete_entity(obj_name)
        time.sleep(0.3)

        self.publish_joint_positions(hover_joints, 2)
        delete_entity("grip_indicator")
        time.sleep(2.0)

        self.publish_joint_positions(tray_hover_joints, 2)
        time.sleep(2.2)
        self.publish_joint_positions(tray_place_joints, 2)
        time.sleep(2.2)

        px, py, _ = self.get_current_tool_xy()
        spawn_entity(obj_name, create_bottle_sdf(obj_name, *color), px, py, 0.01)
        time.sleep(0.5)

        self.publish_joint_positions(tray_hover_joints, 2)
        time.sleep(2.2)
        self.publish_joint_positions(home_joints, 2)

def ros_spin_thread():
    rclpy.init()
    global ros_node
    ros_node = ArmControllerNode()
    rclpy.spin(ros_node)

@app.on_event("startup")
def startup_event():
    threading.Thread(target=ros_spin_thread, daemon=True).start()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)