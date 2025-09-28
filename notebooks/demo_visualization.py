from flask import Flask, render_template_string
from flask_socketio import SocketIO
import threading
import random
from dataclasses import asdict, dataclass
from typing import List, Dict, Optional
from CEFO import BottleneckAgent, ClassroomAgent, Commitment, Offer, compute_slot_map

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
            "violation_threshold": 1,  # Changed from 3 to 1 to match CEFO.py
            "random_seed": 42
        }
        random.seed(self.config["random_seed"])
        self.B = BottleneckAgent(self.config)
        self.classrooms = [ClassroomAgent(f"C{i+1}", self.config["attendance"][i], self.config) 
                          for i in range(self.config["num_classrooms"])]
        self.agents_by_id = {c.id: c for c in self.classrooms}
        
        self.classrooms[3].is_stubborn = True
        
        personalities_str = ', '.join([f'{c.id}:{c.personality}' for c in self.classrooms])
        print(f"System Config: Agent C4 is 'stubborn'. Personalities: {personalities_str}")

sim_state = SimulationState()

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Multi-Agent Traffic Simulation</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }
        
        body { 
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
            margin: 0;
            padding: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
        }
        
        .container { 
            max-width: 1400px; 
            margin: 0 auto;
            background: rgba(255, 255, 255, 0.95);
            border-radius: 15px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
            overflow: hidden;
        }
        
        .header { 
            background: linear-gradient(135deg, #2c3e50 0%, #3498db 100%);
            color: white; 
            padding: 30px; 
            text-align: center;
        }
        
        .header h1 {
            font-size: 2.5em;
            margin-bottom: 10px;
            font-weight: 300;
        }
        
        .header p {
            font-size: 1.1em;
            opacity: 0.9;
        }
        
        .controls { 
            background: white; 
            padding: 25px; 
            border-bottom: 1px solid #eee;
        }
        
        .controls h3 {
            color: #2c3e50;
            margin-bottom: 20px;
            font-size: 1.4em;
        }
        
        .control-buttons {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 20px;
        }
        
        button { 
            padding: 12px 24px; 
            margin: 0;
            border: none; 
            border-radius: 8px; 
            cursor: pointer; 
            font-size: 14px;
            font-weight: 600;
            transition: all 0.3s ease;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        
        button:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 12px rgba(0,0,0,0.15);
        }
        
        .btn-start { background: linear-gradient(135deg, #27ae60, #2ecc71); color: white; }
        .btn-stop { background: linear-gradient(135deg, #e74c3c, #c0392b); color: white; }
        .btn-step { background: linear-gradient(135deg, #3498db, #2980b9); color: white; }
        .btn-reset { background: linear-gradient(135deg, #95a5a6, #7f8c8d); color: white; }
        
        .control-settings {
            display: flex;
            align-items: center;
            gap: 15px;
            flex-wrap: wrap;
        }
        
        .control-settings label {
            font-weight: 600;
            color: #2c3e50;
        }
        
        .control-settings input {
            padding: 8px 12px;
            border: 2px solid #ddd;
            border-radius: 5px;
            font-size: 14px;
            width: 80px;
        }
        
        .status-panel {
            background: #f8f9fa;
            padding: 15px;
            border-radius: 8px;
            margin-top: 15px;
            border-left: 4px solid #3498db;
        }
        
        .charts-container { 
            display: grid; 
            grid-template-columns: 1fr 1fr; 
            gap: 20px; 
            padding: 25px;
        }
        
        @media (max-width: 1200px) {
            .charts-container {
                grid-template-columns: 1fr;
            }
        }
        
        .chart-card { 
            background: white; 
            padding: 20px; 
            border-radius: 10px; 
            box-shadow: 0 5px 15px rgba(0,0,0,0.08);
            border: 1px solid #eee;
        }
        
        .chart-card h3 {
            color: #2c3e50;
            margin-bottom: 15px;
            font-size: 1.2em;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .chart { 
            height: 300px; 
            width: 100%;
        }
        
        /* Agent Status Specific Styles */
        #agentStatus {
            max-height: 300px;
            overflow-y: auto;
            padding-right: 10px;
        }
        
        .agent-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 15px;
            margin-top: 10px;
        }
        
        .agent-card {
            background: linear-gradient(135deg, #f8f9fa, #e9ecef);
            border: 1px solid #dee2e6;
            border-radius: 10px;
            padding: 15px;
            transition: all 0.3s ease;
        }
        
        .agent-card:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
        }
        
        .agent-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }
        
        .agent-name {
            font-size: 1.1em;
            font-weight: 700;
            color: #2c3e50;
        }
        
        .agent-total {
            background: #3498db;
            color: white;
            padding: 4px 8px;
            border-radius: 12px;
            font-size: 0.9em;
            font-weight: 600;
        }
        
        .agent-slots {
            margin-top: 10px;
        }
        
        .slot-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 5px 0;
            border-bottom: 1px solid #eee;
        }
        
        .slot-item:last-child {
            border-bottom: none;
        }
        
        .slot-time {
            font-weight: 600;
            color: #e74c3c;
        }
        
        .slot-count {
            color: #27ae60;
            font-weight: 600;
        }
        
        .logs-container { 
            background: #1a1a1a; 
            color: #00ff00; 
            padding: 25px; 
            border-radius: 0 0 15px 15px;
            border-top: 1px solid #333;
        }
        
        .logs-container h3 {
            color: white;
            margin-bottom: 15px;
            font-size: 1.2em;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        #logContent { 
            height: 250px; 
            overflow-y: auto; 
            font-family: 'Courier New', monospace;
            font-size: 13px;
            line-height: 1.4;
        }
        
        .log-entry {
            padding: 5px 0;
            border-bottom: 1px solid #2a2a2a;
            animation: fadeIn 0.3s ease;
        }
        
        .log-entry:last-child {
            border-bottom: none;
        }
        
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(5px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        /* Scrollbar Styling */
        ::-webkit-scrollbar {
            width: 8px;
        }
        
        ::-webkit-scrollbar-track {
            background: #f1f1f1;
            border-radius: 4px;
        }
        
        ::-webkit-scrollbar-thumb {
            background: #c1c1c1;
            border-radius: 4px;
        }
        
        ::-webkit-scrollbar-thumb:hover {
            background: #a8a8a8;
        }
        
        #logContent::-webkit-scrollbar-track {
            background: #2a2a2a;
        }
        
        #logContent::-webkit-scrollbar-thumb {
            background: #555;
        }
        
        #logContent::-webkit-scrollbar-thumb:hover {
            background: #777;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚦 Multi-Agent Traffic Coordination System</h1>
            <p>Intelligent classroom agents working together to optimize traffic flow and avoid bottlenecks</p>
        </div>
        
        <div class="controls">
            <h3>🎮 Simulation Controls</h3>
            <div class="control-buttons">
                <button class="btn-start" onclick="startSimulation()">▶ Start Simulation</button>
                <button class="btn-stop" onclick="stopSimulation()">⏹ Stop Simulation</button>
                <button class="btn-step" onclick="nextEpisode()">⏭ Next Episode</button>
                <button class="btn-reset" onclick="resetSimulation()">🔄 Reset Simulation</button>
            </div>
            
            <div class="control-settings">
                <label><strong>Episodes to run:</strong></label>
                <input type="number" id="episodesCount" value="3" min="1" max="10">
                <div class="status-panel" id="simulationStatus">
                    <strong>Status:</strong> <span id="statusText">Ready to start simulation</span>
                </div>
            </div>
        </div>

        <div class="charts-container">
            <div class="chart-card">
                <h3>📊 Traffic Distribution</h3>
                <div class="chart" id="trafficChart"></div>
            </div>
            
            <div class="chart-card">
                <h3>🏫 Classroom Schedules</h3>
                <div class="chart" id="scheduleChart"></div>
            </div>
            
            <div class="chart-card">
                <h3>🎭 Agent Personalities</h3>
                <div class="chart" id="personalityChart"></div>
            </div>
            
            <div class="chart-card">
                <h3>🤝 Commitments Tracking</h3>
                <div class="chart" id="commitmentChart"></div>
            </div>
            
            <div class="chart-card">
                <h3>👥 Classroom Agents Status</h3>
                <div class="chart" id="agentStatus">
                    <div style="text-align: center; padding: 50px 20px; color: #666;">
                        <div style="font-size: 3em; margin-bottom: 10px;">👥</div>
                        <div>Waiting for simulation data...</div>
                    </div>
                </div>
            </div>
            
            <div class="chart-card">
                <h3>📈 Reputation Scores</h3>
                <div class="chart" id="reputationChart"></div>
            </div>
        </div>

        <div class="logs-container">
            <h3>📋 Live Agent Interaction Logs</h3>
            <div id="logContent"></div>
        </div>
    </div>

    <script>
        const socket = io();
        let currentData = {};
        
        socket.on('connect', () => {
            addLog('✅ Connected to simulation server');
            updateStatus('Connected and ready');
        });
        
        socket.on('episode_update', (data) => {
            currentData = data;
            updateCharts();
            updateLogs(data.logs);
            updateStatus(`Running Episode ${data.episode}`);
        });
        
        socket.on('simulation_complete', () => {
            addLog('🎉 Simulation completed successfully!');
            updateStatus('Simulation complete');
        });
        
        socket.on('simulation_stopped', () => {
            addLog('⏹️ Simulation stopped by user');
            updateStatus('Simulation stopped');
        });
        
        socket.on('error', (data) => {
            addLog('❌ Error: ' + data.message);
            updateStatus('Error occurred');
        });

        function startSimulation() {
            const episodes = parseInt(document.getElementById('episodesCount').value);
            socket.emit('start_simulation', { episodes });
            updateStatus('Starting simulation...');
        }

        function stopSimulation() {
            socket.emit('stop_simulation');
            updateStatus('Stopping simulation...');
        }

        function nextEpisode() {
            socket.emit('next_episode');
        }

        function resetSimulation() {
            socket.emit('reset_simulation');
            updateStatus('Resetting simulation...');
        }

        function addLog(message) {
            const logContent = document.getElementById('logContent');
            const logEntry = document.createElement('div');
            logEntry.className = 'log-entry';
            logEntry.innerHTML = `[${new Date().toLocaleTimeString()}] ${message}`;
            logContent.appendChild(logEntry);
            logContent.scrollTop = logContent.scrollHeight;
        }

        function updateStatus(message) {
            document.getElementById('statusText').textContent = message;
        }

        function updateLogs(logs) {
            const logContent = document.getElementById('logContent');
            logContent.innerHTML = '';
            logs.forEach(log => addLog(log));
        }

        function updateCharts() {
            updateTrafficChart();
            updateScheduleChart();
            updatePersonalityChart();
            updateCommitmentChart();
            updateReputationChart();
            updateAgentStatus();
        }

        function updateTrafficChart() {
            if (!currentData.slot_map) return;
            
            const offsets = Object.keys(currentData.slot_map).map(Number).sort((a, b) => a - b);
            const students = offsets.map(offset => currentData.slot_map[offset]);
            const colors = students.map(count => count > currentData.capacity ? '#ff6b6b' : '#51cf66');
            
            const trafficTrace = {
                x: offsets,
                y: students,
                type: 'bar',
                name: 'Students',
                marker: { color: colors }
            };
            
            const capacityLine = {
                x: [Math.min(...offsets) - 1, Math.max(...offsets) + 1],
                y: [currentData.capacity, currentData.capacity],
                type: 'scatter',
                mode: 'lines',
                line: { dash: 'dash', color: '#2f3640', width: 3 },
                name: `Capacity: ${currentData.capacity}`
            };
            
            const layout = {
                title: `Episode ${currentData.episode} - Traffic Distribution`,
                xaxis: { title: 'Time Offset (minutes)' },
                yaxis: { title: 'Number of Students' },
                showlegend: true,
                height: 280,
                margin: { t: 40, r: 30, l: 50, b: 50 }
            };
            
            Plotly.newPlot('trafficChart', [trafficTrace, capacityLine], layout);
        }

        function updateScheduleChart() {
            if (!currentData.schedules) return;
            
            const data = [];
            const classrooms = Object.keys(currentData.schedules);
            
            // Define a color palette for classrooms
            const colorPalette = {
                'C1': '#FF6B6B',  // Red
                'C2': '#4ECDC4',  // Teal
                'C3': '#45B7D1',  // Blue
                'C4': '#96CEB4',  // Green
                'C5': '#FFEAA7',  // Yellow
                'C6': '#DDA0DD',  // Plum
                'C7': '#98D8C8',  // Mint
                'C8': '#F7DC6F',  // Light Yellow
                'C9': '#BB8FCE',  // Light Purple
                'C10': '#85C1E9'  // Light Blue
            };
            
            classrooms.forEach(classroom => {
                // Get color from palette or generate a random one if not defined
                const color = colorPalette[classroom] || '#' + Math.floor(Math.random()*16777215).toString(16);
                
                currentData.schedules[classroom].forEach(([offset, count]) => {
                    data.push({
                        x: [offset],
                        y: [classroom],
                        type: 'scatter',
                        mode: 'markers',
                        marker: { 
                            size: Math.max(15, count * 0.8),
                            color: color,
                            line: {
                                color: '#2c3e50',
                                width: 1
                            }
                        },
                        name: classroom,
                        text: [`${classroom}: ${count} students at ${offset} minutes`],
                        hoverinfo: 'text',
                        showlegend: false  // We'll handle legend separately
                    });
                });
            });
            
            // Create legend traces
            const legendTraces = classrooms.map(classroom => {
                const color = colorPalette[classroom] || '#' + Math.floor(Math.random()*16777215).toString(16);
                return {
                    x: [null],
                    y: [null],
                    type: 'scatter',
                    mode: 'markers',
                    marker: {
                        size: 10,
                        color: color,
                        symbol: 'circle'
                    },
                    name: classroom,
                    showlegend: true,
                    hoverinfo: 'none'
                };
            });
            
            const layout = {
                title: 'Classroom Exit Schedules',
                xaxis: { 
                    title: 'Time Offset (minutes)',
                    gridcolor: '#f0f0f0',
                    zerolinecolor: '#f0f0f0'
                },
                yaxis: { 
                    title: 'Classroom',
                    gridcolor: '#f0f0f0',
                    zerolinecolor: '#f0f0f0'
                },
                height: 280,
                margin: { t: 40, r: 30, l: 80, b: 50 },
                plot_bgcolor: 'rgba(248,249,250,0.5)',
                paper_bgcolor: 'rgba(255,255,255,0.8)',
                legend: {
                    orientation: 'h',
                    y: -0.2,
                    x: 0.5,
                    xanchor: 'center'
                }
            };
            
            // Combine data and legend traces
            Plotly.newPlot('scheduleChart', [...data, ...legendTraces], layout);
        }

        function updateCommitmentChart() {
            const commitments = currentData.commitments || [];
            const active = commitments.filter(c => !c.fulfilled);
            const fulfilled = commitments.filter(c => c.fulfilled);
            
            const activeTrace = {
                x: active.map(c => c.proposer + '→' + c.acceptor),
                y: active.map(c => c.moved_students),
                type: 'bar',
                name: 'Active Commitments',
                marker: { color: '#e67e22' }
            };
            
            const fulfilledTrace = {
                x: fulfilled.map(c => c.proposer + '→' + c.acceptor),
                y: fulfilled.map(c => c.moved_students),
                type: 'bar',
                name: 'Fulfilled Commitments',
                marker: { color: '#27ae60' }
            };
            
            const layout = {
                title: `Commitments (${active.length} active, ${fulfilled.length} fulfilled)`,
                xaxis: { title: 'Commitment' },
                yaxis: { title: 'Students Moved' },
                height: 280,
                margin: { t: 40, r: 30, l: 50, b: 100 }
            };
            
            Plotly.newPlot('commitmentChart', [activeTrace, fulfilledTrace], layout);
        }

        function updatePersonalityChart() {
            if (!currentData.agent_info) return;
            
            const personalities = {};
            Object.values(currentData.agent_info).forEach(agent => {
                personalities[agent.personality] = (personalities[agent.personality] || 0) + 1;
            });
            
            const personalityTrace = {
                labels: Object.keys(personalities),
                values: Object.values(personalities),
                type: 'pie',
                marker: {
                    colors: ['#e67e22', '#9b59b6', '#27ae60'] // orange, purple, green
                },
                textinfo: 'label+percent',
                hoverinfo: 'label+value+percent',
                hole: 0.4
            };
            
            const layout = {
                title: 'Agent Personalities Distribution',
                height: 280,
                showlegend: true,
                annotations: [{
                    text: 'Personalities',
                    showarrow: false,
                    font: { size: 14 }
                }]
            };
            
            Plotly.newPlot('personalityChart', [personalityTrace], layout);
        }

        function updateReputationChart() {
            if (!currentData.agent_info) return;
            
            const agents = Object.keys(currentData.agent_info).sort();
            const reputations = agents.map(agent => currentData.agent_info[agent].reputation);
            
            const reputationTrace = {
                x: agents,
                y: reputations,
                type: 'bar',
                marker: {
                    color: reputations.map(rep => {
                        if (rep >= 0.7) return '#27ae60';
                        if (rep >= 0.5) return '#f39c12';
                        return '#e74c3c';
                    })
                }
            };
            
            const layout = {
                title: 'Agent Reputation Scores',
                xaxis: { title: 'Agents' },
                yaxis: { 
                    title: 'Reputation Score',
                    range: [0, 1]
                },
                height: 280
            };
            
            Plotly.newPlot('reputationChart', [reputationTrace], layout);
        }

        function updateAgentStatus() {
            if (!currentData.schedules) return;
            
            const agentStatus = document.getElementById('agentStatus');
            let html = '<div class="agent-grid-vertical">';
            
            Object.keys(currentData.schedules).forEach(agent => {
                const slots = currentData.schedules[agent];
                const totalStudents = slots.reduce((sum, [_, count]) => sum + count, 0);
                const agentInfo = currentData.agent_info ? currentData.agent_info[agent] : null;
                
                if (agentInfo) {
                    const personality = agentInfo.personality;
                    const reputation = agentInfo.reputation;
                    const isStubborn = agentInfo.is_stubborn;
                    const utilityThreshold = agentInfo.utility_threshold;
                    const violations = agentInfo.violations || 0;
                    
                    // Personality display with icons
                    let personalityIcon = '🔄';
                    let personalityText = 'Flexible';
                    let personalityColor = '#27ae60';
                    
                    if (personality === 'prefers_early') {
                        personalityIcon = '⏪';
                        personalityText = 'Prefers Early';
                        personalityColor = '#e67e22';
                    } else if (personality === 'prefers_late') {
                        personalityIcon = '⏩';
                        personalityText = 'Prefers Late';
                        personalityColor = '#9b59b6';
                    }
                    
                    // Reputation color coding
                    let repColor = '#27ae60';
                    if (reputation < 0.7) repColor = '#f39c12';
                    if (reputation < 0.5) repColor = '#e74c3c';
                    
                    html += `
                    <div class="agent-card-vertical">
                        <div class="agent-header-vertical">
                            <div class="agent-name-vertical">${agent}</div>
                            <div class="agent-total-vertical">${totalStudents} students</div>
                        </div>
                        
                        <div class="agent-attributes">
                            <div class="attribute-row">
                                <span class="attribute-label">Personality:</span>
                                <span class="attribute-value" style="color: ${personalityColor}">
                                    ${personalityIcon} ${personalityText}
                                </span>
                            </div>
                            
                            <div class="attribute-row">
                                <span class="attribute-label">Reputation:</span>
                                <span class="attribute-value" style="color: ${repColor}">
                                    ⭐ ${reputation.toFixed(2)}
                                </span>
                            </div>
                            
                            <div class="attribute-row">
                                <span class="attribute-label">Utility Threshold:</span>
                                <span class="attribute-value">📊 ${utilityThreshold}</span>
                            </div>
                            
                            ${isStubborn ? `
                            <div class="attribute-row">
                                <span class="attribute-label">Status:</span>
                                <span class="attribute-value" style="color: #e74c3c">🚫 Stubborn Agent</span>
                            </div>
                            ` : ''}
                            
                            ${violations > 0 ? `
                            <div class="attribute-row">
                                <span class="attribute-label">Violations:</span>
                                <span class="attribute-value" style="color: #e74c3c">⚠️ ${violations}</span>
                            </div>
                            ` : ''}
                        </div>
                        
                        <div class="agent-slots-vertical">
                            <div class="slots-header">Current Schedule:</div>
                            ${slots.map(slot => `
                                <div class="slot-item-vertical">
                                    <span class="slot-time">${slot[0]} min</span>
                                    <span class="slot-count">${slot[1]} students</span>
                                </div>
                            `).join('')}
                        </div>
                    </div>`;
                }
            });
            
            html += '</div>';
            agentStatus.innerHTML = html;
        }

        // Initial message
        addLog('🚀 System initialized. Ready to start simulation.');
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
    
    # Reset all classrooms to initial state
    for classroom in sim_state.classrooms:
        classroom.planned_slots = [(0, classroom.attendance)]
        classroom.commitment_history = []
        # Reset reputation but keep personality and stubborn flag
        classroom.reputation = 1.0
        classroom.is_stubborn = (classroom.id == "C4")
        # Reassign personality (optional - if you want to keep same personalities, remove this)
        # classroom.personality = random.choice(['prefers_early', 'prefers_late', 'flexible'])
    
    socketio.emit('episode_update', get_initial_state())

def run_episode(episode_num):
    logs = []
    ep_tag = f"{sim_state.config['episode_base_name']}_ep{episode_num}"
    
    logs.append(f"Starting Episode {episode_num} ({ep_tag})")
    
    # 1) Broadcast capacity, initial slot assignment = 0
    msg = sim_state.B.broadcast_capacity(sim_state.config["attendance"], ep_tag)
    for c in sim_state.classrooms:
        c.on_capacity_broadcast(msg)
    
    slot_map = compute_slot_map(sim_state.classrooms)
    logs.append(f"[Initial slot map] {slot_map}")
    
    # 2) Fulfill carry-over commitments
    for c in sim_state.classrooms:
        c.fulfill_due_commitments(
            sim_state.commitments_global, 
            current_episode=episode_num,
            slot_map=slot_map, 
            B_agent=sim_state.B, 
            agents_by_id=sim_state.agents_by_id,
            violation_threshold=sim_state.config["violation_threshold"]
        )
    
    slot_map = compute_slot_map(sim_state.classrooms)
    logs.append(f"[After fulfill attempts] slot_map: {slot_map}")
    
    # 3) Enhanced Negotiation rounds with counter-offer logic
    for round_ in range(sim_state.config["max_negotiation_rounds"]):
        slot_map = compute_slot_map(sim_state.classrooms)
        congested_offsets = [off for off, val in slot_map.items() if val > sim_state.B.per_batch]
        
        if not congested_offsets:
            logs.append(f"No congestion after negotiation round {round_} in episode {episode_num}")
            break
            
        logs.append(f"[Negotiation round {round_}] congested offsets: {congested_offsets}")
        
        for off in congested_offsets:
            congested_agents = [c for c in sim_state.classrooms if any(s[0]==off for s in c.planned_slots)]
            
            if len(congested_agents) < 2:
                continue
                
            # Sort by number of students at this offset (descending)
            congested_agents.sort(key=lambda agent: next((s[1] for s in agent.planned_slots if s[0] == off), 0), reverse=True)
            
            a1 = congested_agents[0]
            a2 = congested_agents[1]

            logs.append(f"[{a1.id}] (most students) is proposing to [{a2.id}].")

            # REPUTATION CHECK
            if a2.reputation < 0.5:
                logs.append(f"[{a1.id}] refuses to negotiate with {a2.id} due to low reputation ({a2.reputation:.2f}).")
                continue
                
            offer = a1.propose_shift(a2, off, episode_num, slot_map)
            
            if offer:
                # Calculate utility for the offer
                utility = a2.calculate_utility(offer)
                logs.append(f"[{a2.id}] calculated utility for offer: {utility:.2f} (threshold: {a2.utility_threshold})")
                
                if a2.evaluate_offer(offer):
                    # --- Offer Accepted ---
                    logs.append(f"[{a1.id}]'s offer to shift by {offer.shift_min} min was ACCEPTED by [{a2.id}].")
                    a2.apply_offer(offer)
                    com = Commitment(
                        commitment_id=f"com_{offer.offer_id}",
                        proposer=offer.proposer,
                        acceptor=offer.acceptor,
                        shift_min=offer.shift_min,
                        moved_students=offer.moved_students,
                        created_episode=episode_num,
                        due_episode=episode_num + 1
                    )
                    sim_state.commitments_global.append(com)
                    a1.commitment_history.append(com)
                    a2.commitment_history.append(com)
                    logs.append(f"[COMMITTED] {com.commitment_id} created, due in episode {episode_num+1}.")
                else:
                    # --- Offer Rejected, Initiating Counter-Offer Sequence ---
                    logs.append(f"[{a1.id}]'s offer was REJECTED by [{a2.id}] (utility too low). Checking for a counter-offer...")
                    counter_offer = a2.formulate_counter_offer(offer, episode_num, slot_map)

                    if counter_offer:
                        # a2 made a counter-offer. Now a1 must evaluate it.
                        counter_utility = a1.calculate_utility(counter_offer)
                        logs.append(f"[{a2.id}] counters with a proposal to shift by {counter_offer.shift_min} min.")
                        logs.append(f"[{a1.id}] calculated utility for counter-offer: {counter_utility:.2f} (threshold: {a1.utility_threshold})")
                        
                        if a1.evaluate_offer(counter_offer):
                            # a1 accepts the counter-offer
                            logs.append(f"[{a1.id}] ACCEPTS the counter-offer from [{a2.id}].")
                            a1.apply_offer(counter_offer)
                            com = Commitment(
                                commitment_id=f"com_{counter_offer.offer_id}",
                                proposer=counter_offer.proposer,
                                acceptor=counter_offer.acceptor,
                                shift_min=counter_offer.shift_min,
                                moved_students=counter_offer.moved_students,
                                created_episode=episode_num,
                                due_episode=episode_num + 1
                            )
                            sim_state.commitments_global.append(com)
                            a1.commitment_history.append(com)
                            a2.commitment_history.append(com)
                            logs.append(f"[COMMITTED] {com.commitment_id} created from counter-offer, due in episode {episode_num+1}.")
                        else:
                            # a1 rejects the counter-offer
                            logs.append(f"[{a1.id}] REJECTS the counter-offer from [{a2.id}] (utility too low). Negotiation ends.")
                    else:
                        # a2 did not provide a counter-offer
                        logs.append(f"[{a2.id}] did not provide a counter-offer. Negotiation ends.")
    
    final_slot_map = compute_slot_map(sim_state.classrooms)
    logs.append(f"[Final slot_map after episode] {final_slot_map}")
    logs.append("Schedules:")
    for c in sim_state.classrooms:
        logs.append(f" {c.id}: {c.planned_slots}")
    
    # Include enhanced agent information
    return {
        'episode': episode_num,
        'slot_map': final_slot_map,
        'schedules': {classroom.id: classroom.planned_slots for classroom in sim_state.classrooms},
        'commitments': [asdict(commitment) for commitment in sim_state.commitments_global],
        'capacity': sim_state.B.per_batch,
        'logs': logs,
        'agent_info': {
            classroom.id: {
                'personality': classroom.personality,
                'reputation': classroom.reputation,
                'is_stubborn': classroom.is_stubborn,
                'utility_threshold': classroom.utility_threshold,
                'violations': len([c for c in classroom.commitment_history if c.times_missed > 0])
            } for classroom in sim_state.classrooms
        }
    }

def get_initial_state():
    # Reset to initial state with all classrooms at offset 0
    for classroom in sim_state.classrooms:
        classroom.planned_slots = [(0, classroom.attendance)]
        classroom.commitment_history = []
    
    slot_map = compute_slot_map(sim_state.classrooms)
    
    # Get personalities for initial display
    personalities = [f"{c.id}: {c.personality}" for c in sim_state.classrooms]
    personality_str = ", ".join(personalities)
    
    return {
        'episode': 0,
        'slot_map': slot_map,
        'schedules': {classroom.id: classroom.planned_slots for classroom in sim_state.classrooms},
        'commitments': [asdict(commitment) for commitment in sim_state.commitments_global],
        'capacity': sim_state.B.per_batch,
        'logs': [
            'Multi-Agent Traffic Simulation Ready', 
            'All classrooms start at time offset 0', 
            f'Agent Personalities: {personality_str}',
            'Agent C4 is stubborn (will not fulfill commitments)',
            'Click "Start Simulation" to begin...'
        ],
        'agent_info': {
            classroom.id: {
                'personality': classroom.personality,
                'reputation': classroom.reputation,
                'is_stubborn': classroom.is_stubborn
            } for classroom in sim_state.classrooms
        }
    }


def start_server():
    try:
        print("Starting Multi-Agent Simulation Server...")
        print("Open your browser and go to: http://localhost:5010")
        socketio.run(
            app, 
            host='0.0.0.0', 
            port=5010, 
            debug=False, 
            use_reloader=False,
            allow_unsafe_werkzeug=True
        )
    except Exception as e:
        print(f"Server error: {e}")

if __name__ == "__main__":
    start_server()
