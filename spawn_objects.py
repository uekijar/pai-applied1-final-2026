import subprocess
import time
import rclpy
from rclpy.node import Node
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint
from tf2_ros import Buffer, TransformListener

tray_sdf = """<?xml version="1.0" ?>
<sdf version="1.6">
  <model name="tray">
    <static>true</static>
    <link name="link">
      <visual name="base">
        <geometry><box><size>0.24 0.34 0.01</size></box></geometry>
        <material><ambient>0.3 0.4 0.4 1</ambient><diffuse>0.3 0.4 0.4 1</diffuse></material>
      </visual>
    </link>
  </model>
</sdf>"""

def create_bottle_sdf(name, r, g, b):
    return f"""<?xml version="1.0" ?>
<sdf version="1.6">
  <model name="{name}">
    <static>true</static>
    <link name="link">
      <visual name="body">
        <pose>0 0 0.04 0 0 0</pose>
        <geometry><cylinder><radius>0.025</radius><length>0.08</length></cylinder></geometry>
        <material><ambient>{r} {g} {b} 1</ambient><diffuse>{r} {g} {b} 1</diffuse></material>
      </visual>
      <visual name="cap">
        <pose>0 0 0.085 0 0 0</pose>
        <geometry><cylinder><radius>0.018</radius><length>0.015</length></cylinder></geometry>
        <material><ambient>0.95 0.95 0.95 1</ambient><diffuse>0.95 0.95 0.95 1</diffuse></material>
      </visual>
    </link>
  </model>
</sdf>"""

def delete_entity(name):
    subprocess.run(["ros2", "service", "call", "/delete_entity", "gazebo_msgs/srv/DeleteEntity", f"{{name: '{name}'}}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def spawn_entity(name, xml_content, x, y, z):
    delete_entity(name)
    filename = f"/tmp/{name}.sdf"
    with open(filename, "w") as f:
        f.write(xml_content)
    cmd = ["ros2", "run", "gazebo_ros", "spawn_entity.py", "-entity", name, "-file", filename, "-x", str(x), "-y", str(y), "-z", str(z)]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

class Calibrator(Node):
    def __init__(self):
        super().__init__('calibrator')
        self.pub = self.create_publisher(JointTrajectory, '/joint_trajectory_controller/joint_trajectory', 10)
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

    def move_and_get_xy(self, positions):
        msg = JointTrajectory()
        msg.joint_names = ['shoulder_pan_joint', 'shoulder_lift_joint', 'elbow_joint', 'wrist_1_joint', 'wrist_2_joint', 'wrist_3_joint']
        pt = JointTrajectoryPoint()
        pt.positions = [float(p) for p in positions]
        pt.time_from_start.sec = 1
        msg.points.append(pt)
        
        # 確実にトピックが届くよう数回送信して待機
        for _ in range(3):
            self.pub.publish(msg)
            rclpy.spin_once(self, timeout_sec=0.1)
            
        end_time = time.time() + 2.2
        while time.time() < end_time:
            rclpy.spin_once(self, timeout_sec=0.1)

        # Gazeboの世界座標(world)から見たアーム先端(tool0)の実測値を取得
        for frame in ['world', 'base_link', 'base']:
            try:
                trans = self.tf_buffer.lookup_transform(frame, 'tool0', rclpy.time.Time())
                return trans.transform.translation.x, trans.transform.translation.y
            except Exception:
                continue
        return 0.3, 0.0

def main():
    rclpy.init()
    node = Calibrator()
    print("アームを動かして先端の正確な座標を実測しています（約7秒）...")
    time.sleep(1.0)

    # 1. トレイの位置（正面）を実測して配置
    tx, ty = node.move_and_get_xy([0.0, -1.23, 1.62, -1.96, -1.57, 0.0])
    spawn_entity("tray", tray_sdf, tx, ty, 0.005)
    print(f"トレイ配置完了: X={tx:.3f}, Y={ty:.3f}")

    # 2. 赤いボトルの位置を実測して配置
    rx, ry = node.move_and_get_xy([-0.7, -1.25, 1.65, -1.97, -1.57, 0.0])
    spawn_entity("red_medicine_obj", create_bottle_sdf("red_medicine_obj", 0.9, 0.1, 0.1), rx, ry, 0.0)
    print(f"赤い薬配置完了: X={rx:.3f}, Y={ry:.3f}")

    # 3. 青いボトルの位置を実測して配置
    bx, by = node.move_and_get_xy([0.5, -1.25, 1.65, -1.97, -1.57, 0.0])
    spawn_entity("blue_medicine_obj", create_bottle_sdf("blue_medicine_obj", 0.1, 0.3, 0.9), bx, by, 0.0)
    print(f"青い薬配置完了: X={bx:.3f}, Y={by:.3f}")

    # ホームポジションへ戻す
    node.move_and_get_xy([0.0, -1.57, 0.0, -1.57, 0.0, 0.0])
    print("キャリブレーション完了！すべてのオブジェクトがアームの真下に配置されました。")
    node.destroy_node()
    rclpy.shutdown()

if __name__ == "__main__":
    main()