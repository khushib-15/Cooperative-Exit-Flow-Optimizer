from flask import Flask, render_template_string
from flask_socketio import SocketIO
import threading
import random
from dataclasses import asdict, dataclass
from typing import List, Dict, Optional
from CEFO import BottleneckAgent, ClassroomAgent, Commitment, compute_slot_map

app = Flask(__name__)
app.config['SECRET_KEY'] = 'multiagent_secret_123'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

class SimulationState:
    def __init__(self):
        self.states = []
        self.current_episode = 0
        self.is_running = False
        self.commitments_global = []
        self.config = {
            "episode_base_name": "Monday_11AM",
            "num_classrooms": 6,
            "attendance": [60, 45, 20, 80, 35, 50],
            "bottleneck": {
                "capacity_per_minute": 40,
                "batch_duration_min": 2
            },
            "time_offsets": [0, -2, 2, -4, 4, -6, 6],
            "max_negotiation_rounds": 5,
            "violation_threshold": 3,
            "random_seed": 42
        }
        random.seed(self.config["random_seed"])
        self.B = BottleneckAgent(self.config)
        self.classrooms = [ClassroomAgent(f"C{i+1}", self.config["attendance"][i], self.config) 
                          for i in range(self.config["num_classrooms"])]
        self.agents_by_id = {c.id: c for c in self.classrooms}

sim_state = SimulationState()

HTML_TEMPLATE = ''' 
<!DOCTYPE html>
<html>
<head>
    <title>Multi-Agent Traffic Simulation</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
</head>
<body>
    <h1>Multi-Agent Traffic Coordination System</h1>
    <div id="trafficChart"></div>
    <div id="scheduleChart"></div>
    <div id="commitmentChart"></div>
    <div id="agentStatus"></div>
    <div id="logContent"></div>
    <script>
        const socket = io();
        let currentData = {};
        socket.on('connect', () => { updateStatus('Connected'); });
        socket.on('episode_update', (data) => {
            currentData = data;
            updateStatus('Running Episode ' + data.episode);
        });
        socket.on('simulation_complete', () => { updateStatus('Simulation complete'); });
        socket.on('simulation_stopped', () => { updateStatus('Simulation stopped'); });
        socket.on('error', (data) => { updateStatus('Error: ' + data.message); });
        function updateStatus(msg) { document.getElementById('logContent').innerHTML += msg + "<br>"; }
    </script>
</body>
</html>
'''

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@socketio.on('start_simulation')
def handle_start_simulation(data):
    if sim_state.is_running:
        socketio.emit('error', {'message': 'Simulation is already running'})
        return
    sim_state.is_running = True
    episodes = data.get('episodes', 3)
    def run_simulation():
        try:
            sim_state.states = []
            for ep in range(1, episodes + 1):
                if not sim_state.is_running:
                    break
                state = run_episode(ep)
                sim_state.states.append(state)
                sim_state.current_episode = ep
                socketio.emit('episode_update', state)
                import time; time.sleep(2)
            if sim_state.is_running:
                socketio.emit('simulation_complete')
        except Exception as e:
            socketio.emit('error', {'message': f'Simulation error: {str(e)}'})
        finally:
            sim_state.is_running = False
    thread = threading.Thread(target=run_simulation)
    thread.daemon = True
    thread.start()

@socketio.on('stop_simulation')
def handle_stop_simulation():
    sim_state.is_running = False
    socketio.emit('simulation_stopped')

@socketio.on('next_episode')
def handle_next_episode():
    if sim_state.current_episode < len(sim_state.states):
        sim_state.current_episode += 1
        socketio.emit('episode_update', sim_state.states[sim_state.current_episode - 1])
    else:
        socketio.emit('error', {'message': 'No more episodes available'})

@socketio.on('reset_simulation')
def handle_reset_simulation():
    sim_state.is_running = False
    sim_state.states = []
    sim_state.current_episode = 0
    sim_state.commitments_global = []
    for classroom in sim_state.classrooms:
        classroom.planned_slots = [(0, classroom.attendance)]
        classroom.commitment_history = []
    socketio.emit('episode_update', get_initial_state())

def run_episode(episode_num):
    logs = []
    for classroom in sim_state.classrooms:
        classroom.planned_slots = [(0, classroom.attendance)]
    logs.append(f"Starting Episode {episode_num}")
    slot_map = compute_slot_map(sim_state.classrooms)
    total_students = sum(slot_map.values())
    logs.append(f"Initial traffic: {total_students} students, Capacity: {sim_state.B.per_batch}")
    if total_students > sim_state.B.per_batch:
        logs.append("Congestion detected! Agents negotiating...")
        for i in range(min(2, len(sim_state.classrooms))):
            if i + 1 < len(sim_state.classrooms):
                agent1 = sim_state.classrooms[i]
                agent2 = sim_state.classrooms[i + 1]
                if random.random() < agent2.professor_willingness:
                    offer = agent1.propose_shift(agent2, 0, episode_num)
                    if offer:
                        agent2.apply_offer(offer)
                        commitment = Commitment(
                            commitment_id=f"com_{offer.offer_id}",
                            proposer=agent1.id,
                            acceptor=agent2.id,
                            shift_min=offer.shift_min,
                            moved_students=offer.moved_students,
                            created_episode=episode_num,
                            due_episode=episode_num + 1
                        )
                        sim_state.commitments_global.append(commitment)
                        logs.append(f"{agent1.id} → {agent2.id}: Moved {offer.moved_students} students")
    final_slot_map = compute_slot_map(sim_state.classrooms)
    logs.append(f"Episode {episode_num} complete")
    logs.append(f"Final traffic distribution: {final_slot_map}")
    return {
        'episode': episode_num,
        'slot_map': final_slot_map,
        'schedules': {classroom.id: classroom.planned_slots for classroom in sim_state.classrooms},
        'commitments': [asdict(commitment) for commitment in sim_state.commitments_global],
        'capacity': sim_state.B.per_batch,
        'logs': logs
    }

def get_initial_state():
    slot_map = compute_slot_map(sim_state.classrooms)
    return {
        'episode': 0,
        'slot_map': slot_map,
        'schedules': {classroom.id: classroom.planned_slots for classroom in sim_state.classrooms},
        'commitments': [asdict(commitment) for commitment in sim_state.commitments_global],
        'capacity': sim_state.B.per_batch,
        'logs': ['Multi-Agent Traffic Simulation Ready', 'Click "Start Simulation" to begin...']
    }

def start_server():
    try:
        print("Starting Multi-Agent Simulation Server...")
        print("Open your browser and go to: http://localhost:5005")
        socketio.run(
            app, 
            host='0.0.0.0', 
            port=5005, 
            debug=False, 
            use_reloader=False,
            allow_unsafe_werkzeug=True
        )
    except Exception as e:
        print(f"Server error: {e}")

if __name__ == "__main__":
    start_server()
