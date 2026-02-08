#!/usr/bin/env python

# Copyright (c) 2018-2020 Intel Corporation
#
# This work is licensed under the terms of the MIT license.
# For a copy, see <https://opensource.org/licenses/MIT>.

"""
This module provides the ScenarioManager implementations.
It must not be modified and is for reference only!
"""

from __future__ import print_function
import signal
import sys
import time
import os
import json
import threading

import py_trees
import carla

from srunner.scenariomanager.carla_data_provider import CarlaDataProvider
from srunner.scenariomanager.timer import GameTime
from srunner.scenariomanager.watchdog import Watchdog

from leaderboard.autoagents.agent_wrapper import AgentWrapperFactory, AgentError
from leaderboard.envs.sensor_interface import SensorReceivedNoData
from leaderboard.utils.result_writer import ResultOutputProvider


class ScenarioManager(object):

    """
    Basic scenario manager class. This class holds all functionality
    required to start, run and stop a scenario.
    """

    def __init__(self, timeout, statistics_manager, debug_mode=0):
        self.route_index = None
        self.scenario = None
        self.scenario_tree = None
        self.ego_vehicles = None
        self.other_actors = None

        self._debug_mode = debug_mode
        self._agent_wrapper = None
        self._running = False
        self._timestamp_last_run = 0.0
        self._timeout = float(timeout)

        self.scenario_duration_system = 0.0
        self.scenario_duration_game = 0.0
        self.start_system_time = 0.0
        self.start_game_time = 0.0
        self.end_system_time = 0.0
        self.end_game_time = 0.0

        self._watchdog = None
        self._agent_watchdog = None
        self._scenario_thread = None

        self._statistics_manager = statistics_manager

        # --- 通用采集系统参数 ---
        self._recording_started = False
        self._actor_spawn_buffer = 0
        self._scenario_timestamps = {}
        os.makedirs("logs", exist_ok=True)
        self._timestamp_file = "logs/scenario_timestamps.json"

        signal.signal(signal.SIGINT, self.signal_handler)

    def signal_handler(self, signum, frame):
        if self._agent_watchdog and not self._agent_watchdog.get_status():
            raise RuntimeError("Agent took longer than {}s to send its command".format(self._timeout))
        elif self._watchdog and not self._watchdog.get_status():
            raise RuntimeError("The simulation took longer than {}s to update".format(self._timeout))
        self._running = False

    def cleanup(self):
        self._timestamp_last_run = 0.0
        self.scenario_duration_system = 0.0
        self.scenario_duration_game = 0.0
        self.start_system_time = 0.0
        self.start_game_time = 0.0
        self.end_system_time = 0.0
        self.end_game_time = 0.0

        self._spectator = None
        self._watchdog = None
        self._agent_watchdog = None
        self._recording_started = False
        self._actor_spawn_buffer = 0

    def load_scenario(self, scenario, agent, route_index, rep_number):
        GameTime.restart()
        self._agent_wrapper = AgentWrapperFactory.get_wrapper(agent)
        self.route_index = route_index
        self.scenario = scenario
        self.scenario_tree = scenario.scenario_tree
        self.ego_vehicles = scenario.ego_vehicles
        self.other_actors = scenario.other_actors
        self.repetition_number = rep_number

        self._spectator = CarlaDataProvider.get_world().get_spectator()
        self._agent_wrapper.setup_sensors(self.ego_vehicles[0])

        # 加载 Pass 1 预存的时间戳
        if os.path.exists(self._timestamp_file):
            try:
                with open(self._timestamp_file, 'r') as f:
                    self._scenario_timestamps = json.load(f)
            except Exception:
                self._scenario_timestamps = {}

    def build_scenarios_loop(self, debug):
        while self._running:
            self.scenario.build_scenarios(self.ego_vehicles[0], debug=debug)
            self.scenario.spawn_parked_vehicles(self.ego_vehicles[0])
            time.sleep(1)

    def run_scenario(self):
        self.start_system_time = time.time()
        self.start_game_time = GameTime.get_time()
        self._watchdog = Watchdog(self._timeout)
        self._watchdog.start()
        self._agent_watchdog = Watchdog(self._timeout)
        self._agent_watchdog.start()

        self._running = True
        self._scenario_thread = threading.Thread(target=self.build_scenarios_loop, args=(self._debug_mode > 0, ))
        self._scenario_thread.start()

        while self._running:
            self._tick_scenario()

    def _tick_scenario(self):
        if self._running and self.get_running_status():
            CarlaDataProvider.get_world().tick(self._timeout)

        timestamp = CarlaDataProvider.get_world().get_snapshot().timestamp

        if self._timestamp_last_run < timestamp.elapsed_seconds and self._running:
            self._timestamp_last_run = timestamp.elapsed_seconds
            self._watchdog.update()
            
            # --- 修正点：使用正确的 on_carla_tick 方法名 ---
            GameTime.on_carla_tick(timestamp)
            CarlaDataProvider.on_carla_tick()
            
            self._watchdog.pause()

            try:
                self._agent_watchdog.resume()
                self._agent_watchdog.update()
                ego_action = self._agent_wrapper()
                self._agent_watchdog.pause()
            except Exception as e:
                raise AgentError(e)

            self._watchdog.resume()
            self.ego_vehicles[0].apply_control(ego_action)

            # 1. 驱动剧本树
            py_trees.blackboard.Blackboard().set("AV_control", ego_action, overwrite=True)
            self.scenario_tree.tick_once()

            # 2. 视角控制 (Bird's Eye View 30m)
            # 只有在 ego 存在时才设置
            if self.ego_vehicles and len(self.ego_vehicles) > 0:
                ego_trans = self.ego_vehicles[0].get_transform()
                self._spectator.set_transform(carla.Transform(
                    ego_trans.location + carla.Location(z=30), 
                    carla.Rotation(pitch=-90)
                ))

            # 3. 双阶段通用触发逻辑
            # 3. 极简触发逻辑：仅考虑 Z 轴对齐
            ghost_mode = os.environ.get("GHOST_MODE")
            s_name = self.scenario_tree.name

            if self.scenario_tree.status == py_trees.common.Status.RUNNING:
                if not self._recording_started:
                    
                    world_actors = CarlaDataProvider.get_world().get_actors()
                    ego_loc = self.ego_vehicles[0].get_location()
                    ego_z = ego_loc.z

                    scenario_actors = []
                    for actor in world_actors:
                        # 排除主车
                        if actor.id == self.ego_vehicles[0].id:
                            continue
                        
                        # 获取 role_name 属性（默认为空字符串）
                        role = actor.attributes.get('role_name', '')
                        
                        # 只要 role_name 包含 'scenario' (这是 ScenarioRunner 的默认命名规则)
                        if 'scenario' in role:
                            scenario_actors.append(actor)

                    if ghost_mode == "DETECT" and len(scenario_actors) > 0:
                        # 检查是否所有剧本演员都与主车 Z 轴对齐
                        all_landed = any(abs(a.get_location().z - ego_z) < 0.2 for a in scenario_actors)

                        if all_landed:
                            self._actor_spawn_buffer += 1
                            # 缓冲 3 帧确保稳定
                            if self._actor_spawn_buffer > 3:
                                self._save_trigger_timestamp(s_name, timestamp.elapsed_seconds)
                                self._recording_started = True
                                print(f"🎯 [DETECT] {s_name}: All {len(scenario_actors)} scenario actors landed!")

                    # Pass 2 逻辑
                    if ghost_mode != "DETECT":
                        target_time = self._scenario_timestamps.get(s_name)
                        if target_time and timestamp.elapsed_seconds >= float(target_time):
                            self._start_triggered_recorder()
                            self._recording_started = True

            # 4. 统计更新
            if self._debug_mode > 1:
                self.compute_duration_time()
                self._statistics_manager.compute_route_statistics(
                    self.route_index, 
                    self.scenario_duration_system, 
                    self.scenario_duration_game, 
                    failure_message=""
                )
                self._statistics_manager.write_live_results(
                    self.route_index, 
                    self.ego_vehicles[0].get_velocity().length(), 
                    ego_action, 
                    self.ego_vehicles[0].get_location()
                )

            # 5. 停止逻辑
            if self.scenario_tree.status != py_trees.common.Status.RUNNING:
                if self._recording_started:
                    # 仅在非 DETECT 模式下调用停止录制
                    if os.environ.get("GHOST_MODE") != "DETECT":
                        self._stop_triggered_recorder()
                    
                    self._recording_started = False
                    self._actor_spawn_buffer = 0
                self._running = False

    def _start_triggered_recorder(self):
        """开启正式录制与数据保存"""
        if not os.path.exists("logs"):
            os.makedirs("logs")
        s_name = self.scenario_tree.name if self.scenario_tree else "scenario"
        
        # 通知 DataAgent 保存数据
        py_trees.blackboard.Blackboard().set("scenario_triggered", True)
        
        # 启动 CARLA 录制器
        CarlaDataProvider.get_client().start_recorder(os.path.abspath("logs/{}.log".format(s_name)))
        print("🎬 [BLOCK] Record started for {}".format(s_name))

    def _stop_triggered_recorder(self):
        """停止录制与数据保存"""
        py_trees.blackboard.Blackboard().set("scenario_triggered", False)
        CarlaDataProvider.get_client().stop_recorder()
        print("🛑 [BLOCK] Record stopped.")

    def _save_trigger_timestamp(self, s_name, timestamp):
        """保存探测到的时间戳"""
        if not os.path.exists("logs"):
            os.makedirs("logs")
        data = {}
        if os.path.exists(self._timestamp_file):
            try:
                with open(self._timestamp_file, 'r') as f:
                    data = json.load(f)
            except Exception:
                data = {}
        
        data[s_name] = timestamp
        
        with open(self._timestamp_file, 'w') as f:
            json.dump(data, f, indent=4)
        print("💾 [DETECT] Saved {} trigger at {}s".format(s_name, timestamp))

    def get_running_status(self):
        if self._watchdog:
            return self._watchdog.get_status()
        return True

    def stop_scenario(self):
        if self._watchdog:
            self._watchdog.stop()
        if self._agent_watchdog:
            self._agent_watchdog.stop()
        
        self.compute_duration_time()
        
        if self.get_running_status():
            if self.scenario is not None:
                self.scenario.terminate()
            if self._agent_wrapper is not None:
                self._agent_wrapper.cleanup()
                self._agent_wrapper = None
            self.analyze_scenario()
        
        self._running = False
        if self._scenario_thread:
            self._scenario_thread.join()
            self._scenario_thread = None

    def compute_duration_time(self):
        self.end_system_time = time.time()
        self.end_game_time = GameTime.get_time()
        self.scenario_duration_system = self.end_system_time - self.start_system_time
        self.scenario_duration_game = self.end_game_time - self.start_game_time

    def analyze_scenario(self):
        ResultOutputProvider(self)