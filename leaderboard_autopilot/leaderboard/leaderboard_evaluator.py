#!/usr/bin/env python
# Copyright (c) 2018-2019 Intel Corporation.
# authors: German Ros (german.ros@intel.com), Felipe Codevilla (felipe.alcm@gmail.com)
#
# This work is licensed under the terms of the MIT license.
# For a copy, see <https://opensource.org/licenses/MIT>.

"""
CARLA Challenge Evaluator Routes

Provisional code to evaluate Autonomous Agents for the CARLA Autonomous Driving challenge
"""
from __future__ import print_function

import traceback
import argparse
from argparse import RawTextHelpFormatter
from distutils.version import LooseVersion
import importlib
import os
import pkg_resources
import sys
import carla
import signal

from srunner.scenariomanager.carla_data_provider import *
from srunner.scenariomanager.timer import GameTime
from srunner.scenariomanager.watchdog import Watchdog

from leaderboard.scenarios.scenario_manager import ScenarioManager
from leaderboard.scenarios.route_scenario import RouteScenario
from leaderboard.envs.sensor_interface import SensorConfigurationInvalid
from leaderboard.autoagents.agent_wrapper import AgentError, validate_sensor_configuration
from leaderboard.utils.statistics_manager import StatisticsManager, FAILURE_MESSAGES
from leaderboard.utils.route_indexer import RouteIndexer

import json
import os
import carla
import math
from srunner.scenariomanager.carla_data_provider import CarlaDataProvider

import json
import os
import carla
import math
from srunner.scenariomanager.carla_data_provider import CarlaDataProvider

# === 全局追踪容器 ===
PENDING_GHOSTS = {}   
DETECTED_GHOSTS = set() 
# 记录 ID -> 蓝图ID (只记录那些出生在原点的车)
LAZY_SPAWN_TRACKER = {} 
IS_MANUAL_STOP = False   

# 辅助函数：计算指纹坐标与目标的距离
def is_close_to_blacklist(location, threshold=1.0):
    if not hasattr(CarlaDataProvider, '_blacklist'): return False
    
    # 预解析黑名单坐标 (建议在加载时做，这里为了代码紧凑写在一起)
    if not hasattr(CarlaDataProvider, '_parsed_blacklist'):
        CarlaDataProvider._parsed_blacklist = []
        for fp in CarlaDataProvider._blacklist:
            try:
                parts = fp.split('_')
                # 假设格式：bp_x_y_z (取最后三个为坐标)
                x, y = float(parts[-3]), float(parts[-2])
                CarlaDataProvider._parsed_blacklist.append((x, y))
            except: continue

    curr_x, curr_y = location.x, location.y
    for bx, by in CarlaDataProvider._parsed_blacklist:
        # 使用欧几里得距离平方优化性能
        if (curr_x - bx)**2 + (curr_y - by)**2 < (threshold * threshold):
            return True
    return False

# ==============================================================================
# PASS 1: 侦测模式 (DETECT) - 记录“真实起点”
# ==============================================================================
if os.environ.get("GHOST_MODE") == "DETECT":
    print("🕵️  GHOST MODE: DETECT (Real-Start-Point Recording)")

    # 1. 劫持单体生成：区分“真出生”和“懒加载”
    _original_spawn_actor = carla.World.spawn_actor
    _original_try_spawn = carla.World.try_spawn_actor

    def wrap_spawn(original_func):
        def new_spawn(self, blueprint, transform, *args, **kwargs):
            actor = original_func(self, blueprint, transform, *args, **kwargs)
            if actor and hasattr(actor, 'type_id') and 'vehicle' in actor.type_id:
                
                # A. 懒加载 (0,0,0)：暂不记录指纹，加入追踪名单
                if transform.location.distance(carla.Location(0,0,0)) < 1.0:
                    LAZY_SPAWN_TRACKER[actor.id] = blueprint.id
                
                # B. 正常生成：直接记录出生点为指纹
                else:
                    fp = CarlaDataProvider.get_fingerprint(blueprint.id, transform)
                    CarlaDataProvider._spawn_registry[actor.id] = fp
            return actor
        return new_spawn

    carla.World.spawn_actor = wrap_spawn(_original_spawn_actor)
    carla.World.try_spawn_actor = wrap_spawn(_original_try_spawn)

    # 2. 劫持批量生成 (逻辑同上)
    _original_apply_batch_sync = carla.Client.apply_batch_sync
    def new_apply_batch_sync(self, commands, tick=False):
        responses = _original_apply_batch_sync(self, commands, tick)
        for i, cmd in enumerate(commands):
            if isinstance(cmd, carla.command.SpawnActor) and not responses[i].has_error():
                aid = responses[i].actor_id
                
                bp_obj = getattr(cmd, 'blueprint', None)
                bp_id = bp_obj.id if bp_obj else "unknown"

                # 检查坐标
                loc = cmd.transform.location
                if loc.distance(carla.Location(0,0,0)) < 1.0:
                    LAZY_SPAWN_TRACKER[aid] = bp_id
                else:
                    # 非原点，直接注册
                    if aid not in CarlaDataProvider._spawn_registry:
                        fp = CarlaDataProvider.get_fingerprint(bp_id, cmd.transform)
                        CarlaDataProvider._spawn_registry[aid] = fp
        return responses
    carla.Client.apply_batch_sync = new_apply_batch_sync

    # 3. 劫持位移 (set_transform)：确定懒加载车辆的“真实户口”
    _original_set_transform = carla.Actor.set_transform
    def detective_set_transform(self, transform):
        try:
            if 'vehicle' in self.type_id:
                
                # CASE A: 懒加载车辆的“第一次着陆”
                if self.id in LAZY_SPAWN_TRACKER:
                    # 这就是它的真实起点！现在记录指纹
                    bp_id = LAZY_SPAWN_TRACKER.pop(self.id) # 移出追踪，避免重复
                    fp = CarlaDataProvider.get_fingerprint(bp_id, transform)
                    CarlaDataProvider._spawn_registry[self.id] = fp
                    # print(f"📍 [户口登记] ID {self.id} 真实起点已锁定: {fp}")

                # CASE B: 已有户口的车辆发生异常位移 (抓鬼)
                elif self.id in CarlaDataProvider._spawn_registry:
                    curr_loc = self.get_location()
                    if curr_loc.distance(transform.location) > 10.0:
                        spawn_fp = CarlaDataProvider._spawn_registry[self.id]
                        if spawn_fp not in DETECTED_GHOSTS:
                            print(f"👻 [捕获幽灵] ID {self.id} 瞬移异常 -> 拉黑真实起点: {spawn_fp}")
                            DETECTED_GHOSTS.add(spawn_fp)
        except: pass
        return _original_set_transform(self, transform)
    carla.Actor.set_transform = detective_set_transform

    # 4. 销毁/掉落监控 (逻辑不变，但现在使用的是“真实起点”指纹)
    _original_destroy = carla.Actor.destroy
    def detective_destroy(self):
        if hasattr(self, 'id') and self.id in CarlaDataProvider._spawn_registry:
            PENDING_GHOSTS[self.id] = CarlaDataProvider._spawn_registry[self.id]
        return _original_destroy(self)
    carla.Actor.destroy = detective_destroy

    _original_world_tick = carla.World.tick
    def detective_world_tick(self, *args, **kwargs):
        global PENDING_GHOSTS, DETECTED_GHOSTS
        if PENDING_GHOSTS and not IS_MANUAL_STOP:
            for actor_id, fp in PENDING_GHOSTS.items():
                print(f"⚰️  [确认销毁] ID {actor_id} -> 拉黑")
                DETECTED_GHOSTS.add(fp)
            PENDING_GHOSTS.clear()
            
        try:
            for actor_id, actor in list(CarlaDataProvider._carla_actor_pool.items()):
                if actor_id in CarlaDataProvider._spawn_registry:
                    if isinstance(actor, carla.Vehicle) and actor.get_location().z < -10:
                        fp = CarlaDataProvider._spawn_registry[actor_id]
                        if fp not in DETECTED_GHOSTS:
                            print(f"📉 [物理掉落] ID {actor_id} -> 拉黑")
                            DETECTED_GHOSTS.add(fp)
        except: pass
        return _original_world_tick(self, *args, **kwargs)
    carla.World.tick = detective_world_tick


# ==============================================================================
# PASS 2: 拦截模式 (BLOCK) - 针对“真实起点”进行封锁
# ==============================================================================
elif os.environ.get("GHOST_MODE") == "BLOCK":
    print("🛡️  GHOST MODE: BLOCK (Real-Start Blocking)")
    
    # 1. 加载并预解析黑名单坐标
    BLACKLIST_COORDS = []
    try:
        if os.path.exists("ghost_blacklist.json"):
            with open("ghost_blacklist.json", "r") as f:
                raw_list = json.load(f)
                CarlaDataProvider._blacklist = set(raw_list)
                
            # 预提取坐标，避免循环内字符串处理
            for fp in CarlaDataProvider._blacklist:
                try:
                    parts = fp.split('_')
                    # 格式通常是 ID_x_y_z，取倒数第3和第2位
                    x, y = float(parts[-3]), float(parts[-2])
                    BLACKLIST_COORDS.append((x, y))
                except: continue
            print(f"📋 黑名单坐标已提取: {len(BLACKLIST_COORDS)} 个点位")
    except Exception as e:
        print(f"⚠️ 黑名单加载失败: {e}")

    # 辅助函数：纯坐标比对
    def is_location_blacklisted(location):
        if not location: return False
        x, y = location.x, location.y
        # 0.5米半径拦截
        for bx, by in BLACKLIST_COORDS:
            if (x - bx)**2 + (y - by)**2 < 0.25:
                return True
        return False

    # -------------------------------------------------------------------------
    # A. 拦截单体生成 (spawn_actor)
    # -------------------------------------------------------------------------
    _original_spawn_actor = carla.World.spawn_actor
    _original_try_spawn = carla.World.try_spawn_actor

    def wrap_block_spawn(original_func):
        def new_spawn(self, blueprint, transform, *args, **kwargs):
            # 1. 【安全网】如果是剧情关键角色，无条件放行！
            # 这是为了解决问题2：即使坐标在黑名单，只要是剧情车，必须让它过。
            important_roles = ['scenario', 'hero']  # 可以根据实际情况调整关键词
            if blueprint.has_attribute('role_name'):
                if any(role in blueprint.get_attribute('role_name').as_str() for role in important_roles):
                    return original_func(self, blueprint, transform, *args, **kwargs)

            # 2. 【安全网】传感器无条件放行
            if blueprint.id.startswith('sensor.'):
                return original_func(self, blueprint, transform, *args, **kwargs)

            # 3. 懒加载策略：原点 (0,0,0) 放行 (依靠后续 set_transform 拦截)
            if transform.location.distance(carla.Location(0,0,0)) < 1.0:
                actor = original_func(self, blueprint, transform, *args, **kwargs)
                if actor: 
                    LAZY_SPAWN_TRACKER[actor.id] = True
                return actor

            # 4. 核心拦截：只看坐标
            if is_location_blacklisted(transform.location):
                print(f"🚫 [单体拦截] 坐标命中黑名单: ({transform.location.x:.1f}, {transform.location.y:.1f})")
                return None
            
            return original_func(self, blueprint, transform, *args, **kwargs)
        return new_spawn

    carla.World.spawn_actor = wrap_block_spawn(_original_spawn_actor)
    carla.World.try_spawn_actor = wrap_block_spawn(_original_try_spawn)

    # -------------------------------------------------------------------------
    # B. 拦截批量生成 (apply_batch) - 彻底移除 blueprint 访问，修复崩溃
    # -------------------------------------------------------------------------
    def filter_batch_commands(commands):
        safe_cmds = []
        for cmd in commands:
            if isinstance(cmd, carla.command.SpawnActor):
                # 1. 懒加载放行：原点 (0,0,0)
                if cmd.transform.location.distance(carla.Location(0,0,0)) < 1.0:
                    safe_cmds.append(cmd)
                    continue

                # 2. 核心拦截：只看坐标 (完全不访问 cmd.blueprint，彻底杜绝 AttributeError)
                if is_location_blacklisted(cmd.transform.location):
                    # 批量生成的通常是背景车，直接杀，不需要顾虑剧情车
                    # (剧情车通常由 ScenarioRunner 通过 spawn_actor 单独生成)
                    print(f"🚫 [批量拦截] 坐标命中黑名单: ({cmd.transform.location.x:.1f}, {cmd.transform.location.y:.1f})")
                    continue
            
            # 非生成指令或安全的生成指令，保留
            safe_cmds.append(cmd)
        return safe_cmds

    # 劫持入口
    _original_apply_batch = carla.Client.apply_batch
    carla.Client.apply_batch = lambda self, cmds: _original_apply_batch(self, filter_batch_commands(cmds))

    _original_apply_batch_sync = carla.Client.apply_batch_sync
    # 增加钩子以在批量生成后记录懒加载 ID
    def block_apply_batch_sync(self, commands, tick=False):
        filtered = filter_batch_commands(commands)
        responses = _original_apply_batch_sync(self, filtered, tick)
        # 补录懒加载 ID
        for i, cmd in enumerate(filtered):
            if isinstance(cmd, carla.command.SpawnActor) and not responses[i].has_error():
                if cmd.transform.location.distance(carla.Location(0,0,0)) < 1.0:
                    LAZY_SPAWN_TRACKER[responses[i].actor_id] = True
        return responses
    carla.Client.apply_batch_sync = block_apply_batch_sync

    # -------------------------------------------------------------------------
    # C. 拦截懒加载瞬移 (set_transform) - 逻辑不变
    # -------------------------------------------------------------------------
    _original_set_transform = carla.Actor.set_transform
    def block_set_transform(self, transform):
        try:
            if self.id in LAZY_SPAWN_TRACKER:
                if is_location_blacklisted(transform.location):
                    print(f"🚫 [瞬移拦截] 懒加载车辆前往黑名单坐标 -> 销毁: ({transform.location.x:.1f}, {transform.location.y:.1f})")
                    self.destroy()
                    del LAZY_SPAWN_TRACKER[self.id]
                    return
                del LAZY_SPAWN_TRACKER[self.id]
        except: pass
        return _original_set_transform(self, transform)
    carla.Actor.set_transform = block_set_transform

sensors_to_icons = {
    'sensor.camera.rgb':        'carla_camera',
    'sensor.lidar.ray_cast':    'carla_lidar',
    'sensor.other.radar':       'carla_radar',
    'sensor.other.gnss':        'carla_gnss',
    'sensor.other.imu':         'carla_imu',
    'sensor.opendrive_map':     'carla_opendrive_map',
    'sensor.speedometer':       'carla_speedometer',
    'sensor.camera.semantic_segmentation': 'carla_camera', 
    'sensor.camera.depth':      'carla_camera', # 如果你以后用深度图，顺便也加上
    'sensor.camera.instance_segmentation': 'carla_camera', # 实例分割同理
}

class LeaderboardEvaluator(object):
    """
    Main class of the Leaderboard. Everything is handled from here,
    from parsing the given files, to preparing the simulation, to running the route.
    """

    # Tunable parameters
    client_timeout = 10.0  # in seconds
    frame_rate = 20.0      # in Hz

    def __init__(self, args, statistics_manager):
        """
        Setup CARLA client and world
        Setup ScenarioManager
        """
        self.world = None
        self.manager = None
        self.sensors = None
        self.sensors_initialized = False
        self.sensor_icons = []
        self.agent_instance = None
        self.route_scenario = None

        self.statistics_manager = statistics_manager

        # This is the ROS1 bridge server instance. This is not encapsulated inside the ROS1 agent because the same
        # instance is used on all the routes (i.e., the server is not restarted between routes). This is done
        # to avoid reconnection issues between the server and the roslibpy client.
        self._ros1_server = None

        # Setup the simulation
        self.client, self.client_timeout, self.traffic_manager = self._setup_simulation(args)

        dist = pkg_resources.get_distribution("carla")
        if dist.version != 'leaderboard':
            if LooseVersion(dist.version) < LooseVersion('0.9.10'):
                raise ImportError("CARLA version 0.9.10.1 or newer required. CARLA version found: {}".format(dist))

        # Load agent
        module_name = os.path.basename(args.agent).split('.')[0]
        sys.path.insert(0, os.path.dirname(args.agent))
        self.module_agent = importlib.import_module(module_name)

        # Create the ScenarioManager
        self.manager = ScenarioManager(args.timeout, self.statistics_manager, args.debug)

        # Time control for summary purposes
        self._start_time = GameTime.get_time()
        self._end_time = None

        # Prepare the agent timer
        self._agent_watchdog = None
        signal.signal(signal.SIGINT, self._signal_handler)

        self._client_timed_out = False

    def _signal_handler(self, signum, frame):
        """
        Terminate scenario ticking when receiving a signal interrupt.
        Either the agent initialization watchdog is triggered, or the runtime one at scenario manager
        """
        if self._agent_watchdog and not self._agent_watchdog.get_status():
            raise RuntimeError("Timeout: Agent took longer than {}s to setup".format(self.client_timeout))
        elif self.manager:
            self.manager.signal_handler(signum, frame)

    def __del__(self):
        """
        Cleanup and delete actors, ScenarioManager and CARLA world
        """
        if hasattr(self, 'manager') and self.manager:
            del self.manager
        if hasattr(self, 'world') and self.world:
            del self.world

    def _get_running_status(self):
        """
        returns:
           bool: False if watchdog exception occured, True otherwise
        """
        if self._agent_watchdog:
            return self._agent_watchdog.get_status()
        return False

    def _cleanup(self):
        """
        Remove and destroy all actors
        """
        global PENDING_GHOSTS
        if PENDING_GHOSTS:
            print(f"🏁 判定：待定区内有 {len(PENDING_GHOSTS)} 辆车属于正常散场，已豁免。")
            PENDING_GHOSTS.clear()
        CarlaDataProvider.cleanup()

        if self._agent_watchdog:
            self._agent_watchdog.stop()

        try:
            if self.agent_instance:
                self.agent_instance.destroy()
                self.agent_instance = None
        except Exception as e:
            print("\n\033[91mFailed to stop the agent:")
            print(f"\n{traceback.format_exc()}\033[0m")

        if self.route_scenario:
            self.route_scenario.remove_all_actors()
            self.route_scenario = None
            if self.statistics_manager:
                self.statistics_manager.remove_scenario()

        if self.manager:
            self._client_timed_out = not self.manager.get_running_status()
            self.manager.cleanup()

        # Make sure no sensors are left streaming
        alive_sensors = self.world.get_actors().filter('*sensor*')
        for sensor in alive_sensors:
            sensor.stop()
            sensor.destroy()

    def _setup_simulation(self, args):
        """
        Prepares the simulation by getting the client, and setting up the world and traffic manager settings
        """
        client = carla.Client(args.host, args.port)
        if args.timeout:
            client_timeout = args.timeout
        client.set_timeout(client_timeout)

        settings = carla.WorldSettings(
            synchronous_mode = True,
            fixed_delta_seconds = 1.0 / self.frame_rate,
            deterministic_ragdolls = True,
            spectator_as_ego = False
        )
        client.get_world().apply_settings(settings)

        traffic_manager = client.get_trafficmanager(args.traffic_manager_port)
        traffic_manager.set_synchronous_mode(True)
        traffic_manager.set_hybrid_physics_mode(True)

        return client, client_timeout, traffic_manager

    def _reset_world_settings(self):
        """
        Changes the modified world settings back to asynchronous
        """
        # Has simulation failed?
        if self.world and self.manager and not self._client_timed_out:
            # Reset to asynchronous mode
            self.world.tick()  # TODO: Make sure all scenario actors have been destroyed
            settings = self.world.get_settings()
            settings.synchronous_mode = False
            settings.fixed_delta_seconds = None
            settings.deterministic_ragdolls = False
            settings.spectator_as_ego = True
            self.world.apply_settings(settings)

            # Make the TM back to async
            self.traffic_manager.set_synchronous_mode(False)
            self.traffic_manager.set_hybrid_physics_mode(False)

    def _load_and_wait_for_world(self, args, town):
        """
        Load a new CARLA world without changing the settings and provide data to CarlaDataProvider
        """
        self.world = self.client.load_world(town, reset_settings=False)

        # Large Map settings are always reset, for some reason
        settings = self.world.get_settings()
        settings.tile_stream_distance = 650
        settings.actor_active_distance = 650
        self.world.apply_settings(settings)

        self.world.reset_all_traffic_lights()
        CarlaDataProvider.set_client(self.client)
        CarlaDataProvider.set_traffic_manager_port(args.traffic_manager_port)
        CarlaDataProvider.set_world(self.world)

        # This must be here so that all route repetitions use the same 'unmodified' seed
        self.traffic_manager.set_random_device_seed(args.traffic_manager_seed)

        # Wait for the world to be ready
        self.world.tick()

        map_name = CarlaDataProvider.get_map().name.split("/")[-1]
        if map_name != town:
            raise Exception("The CARLA server uses the wrong map!"
                            " This scenario requires the use of map {}".format(town))

    def _register_statistics(self, route_index, entry_status, crash_message=""):
        """
        Computes and saves the route statistics
        """
        print("\033[1m> Registering the route statistics\033[0m")
        self.statistics_manager.save_entry_status(entry_status)
        self.statistics_manager.compute_route_statistics(
            route_index, self.manager.scenario_duration_system, self.manager.scenario_duration_game, crash_message
        )

    def _load_and_run_scenario(self, args, config):
        """
        Load and run the scenario given by config.

        Depending on what code fails, the simulation will either stop the route and
        continue from the next one, or report a crash and stop.
        """
        global IS_MANUAL_STOP
        IS_MANUAL_STOP = False
        crash_message = ""
        entry_status = "Started"

        print("\n\033[1m========= Preparing {} (repetition {}) =========\033[0m".format(config.name, config.repetition_index))

        # Prepare the statistics of the route
        route_name = f"{config.name}_rep{config.repetition_index}"
        self.statistics_manager.create_route_data(route_name, config.index)

        print("\033[1m> Loading the world\033[0m")

        # Load the world and the scenario
        try:
            self._load_and_wait_for_world(args, config.town)
            self.route_scenario = RouteScenario(world=self.world, config=config, debug_mode=args.debug)
            self.statistics_manager.set_scenario(self.route_scenario)

        except Exception:
            # The scenario is wrong -> set the ejecution to crashed and stop
            print("\n\033[91mThe scenario could not be loaded:")
            print(f"\n{traceback.format_exc()}\033[0m")

            entry_status, crash_message = FAILURE_MESSAGES["Simulation"]
            self._register_statistics(config.index, entry_status, crash_message)
            self._cleanup()
            return True

        print("\033[1m> Setting up the agent\033[0m")

        # Set up the user's agent, and the timer to avoid freezing the simulation
        try:
            self._agent_watchdog = Watchdog(args.timeout)
            self._agent_watchdog.start()
            agent_class_name = getattr(self.module_agent, 'get_entry_point')()
            agent_class_obj = getattr(self.module_agent, agent_class_name)

            # Start the ROS1 bridge server only for ROS1 based agents.
            if getattr(agent_class_obj, 'get_ros_version')() == 1 and self._ros1_server is None:
                from leaderboard.autoagents.ros1_agent import ROS1Server
                self._ros1_server = ROS1Server()
                self._ros1_server.start()

            self.agent_instance = agent_class_obj(args.agent_config)
            self.agent_instance.set_global_plan(self.route_scenario.gps_route, self.route_scenario.route)
            self.agent_instance.setup(args.agent_config)

            # Check and store the sensors
            if not self.sensors:
                self.sensors = self.agent_instance.sensors()
                track = self.agent_instance.track

                # validate_sensor_configuration(self.sensors, track, args.track)

                self.sensor_icons = [sensors_to_icons[sensor['type']] for sensor in self.sensors]
                self.statistics_manager.save_sensors(self.sensor_icons)
                self.statistics_manager.write_statistics()

                self.sensors_initialized = True

            self._agent_watchdog.stop()
            self._agent_watchdog = None

        except SensorConfigurationInvalid as e:
            # The sensors are invalid -> set the ejecution to rejected and stop
            print("\n\033[91mThe sensor's configuration used is invalid:")
            print(f"{e}\033[0m\n")

            entry_status, crash_message = FAILURE_MESSAGES["Sensors"]
            self._register_statistics(config.index, entry_status, crash_message)
            self._cleanup()
            return True

        except Exception:
            # The agent setup has failed -> start the next route
            print("\n\033[91mCould not set up the required agent:")
            print(f"\n{traceback.format_exc()}\033[0m")

            entry_status, crash_message = FAILURE_MESSAGES["Agent_init"]
            self._register_statistics(config.index, entry_status, crash_message)
            self._cleanup()
            return False

        print("\033[1m> Running the route\033[0m")

        # Run the scenario
        try:
            # Load scenario and run it
            if args.record:
                self.client.start_recorder("{}/{}_rep{}.log".format(args.record, config.name, config.repetition_index))
            self.manager.load_scenario(self.route_scenario, self.agent_instance, config.index, config.repetition_index)
            self.manager.run_scenario()
            IS_MANUAL_STOP = True

        except AgentError:
            # The agent has failed -> stop the route
            print("\n\033[91mStopping the route, the agent has crashed:")
            print(f"\n{traceback.format_exc()}\033[0m")

            entry_status, crash_message = FAILURE_MESSAGES["Agent_runtime"]

        except Exception:
            print("\n\033[91mError during the simulation:")
            print(f"\n{traceback.format_exc()}\033[0m")

            entry_status, crash_message = FAILURE_MESSAGES["Simulation"]

        # Stop the scenario
        try:
            print("\033[1m> Stopping the route\033[0m")
            self.manager.stop_scenario()
            self._register_statistics(config.index, entry_status, crash_message)

            if args.record:
                self.client.stop_recorder()

            self._cleanup()

        except Exception:
            print("\n\033[91mFailed to stop the scenario, the statistics might be empty:")
            print(f"\n{traceback.format_exc()}\033[0m")

            _, crash_message = FAILURE_MESSAGES["Simulation"]

        # If the simulation crashed, stop the leaderboard, for the rest, move to the next route
        return crash_message == "Simulation crashed"

    def run(self, args):
        """
        Run the challenge mode
        """
        route_indexer = RouteIndexer(args.routes, args.repetitions, args.routes_subset)

        if args.resume:
            resume = route_indexer.validate_and_resume(args.checkpoint)
        else:
            resume = False

        if resume:
            self.statistics_manager.add_file_records(args.checkpoint)
        else:
            self.statistics_manager.clear_records()
        self.statistics_manager.save_progress(route_indexer.index, route_indexer.total)
        self.statistics_manager.write_statistics()

        crashed = False
        while route_indexer.peek() and not crashed:

            # Run the scenario
            config = route_indexer.get_next_config()
            crashed = self._load_and_run_scenario(args, config)

            # Save the progress and write the route statistics
            self.statistics_manager.save_progress(route_indexer.index, route_indexer.total)
            self.statistics_manager.write_statistics()

        # Shutdown ROS1 bridge server if necessary
        if self._ros1_server is not None:
            self._ros1_server.shutdown()

        # Go back to asynchronous mode
        self._reset_world_settings()

        if not crashed:
            # Save global statistics
            print("\033[1m> Registering the global statistics\033[0m")
            self.statistics_manager.compute_global_statistics()
            self.statistics_manager.validate_and_write_statistics(self.sensors_initialized, crashed)

        return crashed
    
    def _audit_ghosts(self):
        """
        审核函数：如果这一帧还在跑，那么上一帧待定区里的车就是真正的“鬼”
        """
        global PENDING_GHOSTS, DETECTED_GHOSTS
        if PENDING_GHOSTS:
            for actor_id, fp in PENDING_GHOSTS.items():
                print(f"🕵️  审核通过：检测到数据继续产生，确认 ID {actor_id} 为异常消失 -> 加入黑名单")
                DETECTED_GHOSTS.add(fp)
            PENDING_GHOSTS.clear() # 审核完清空

def main():
    description = "CARLA AD Leaderboard Evaluation: evaluate your Agent in CARLA scenarios\n"

    # general parameters
    parser = argparse.ArgumentParser(description=description, formatter_class=RawTextHelpFormatter)
    parser.add_argument('--host', default='localhost',
                        help='IP of the host server (default: localhost)')
    parser.add_argument('--port', default=2000, type=int,
                        help='TCP port to listen to (default: 2000)')
    parser.add_argument('--traffic-manager-port', default=8000, type=int,
                        help='Port to use for the TrafficManager (default: 8000)')
    parser.add_argument('--traffic-manager-seed', default=0, type=int,
                        help='Seed used by the TrafficManager (default: 0)')
    parser.add_argument('--debug', type=int,
                        help='Run with debug output', default=0)
    parser.add_argument('--record', type=str, default='',
                        help='Use CARLA recording feature to create a recording of the scenario')
    parser.add_argument('--timeout', default=300.0, type=float,
                        help='Set the CARLA client timeout value in seconds')

    # simulation setup
    parser.add_argument('--routes', required=True,
                        help='Name of the routes file to be executed.')
    parser.add_argument('--routes-subset', default='', type=str,
                        help='Execute a specific set of routes')
    parser.add_argument('--repetitions', type=int, default=1,
                        help='Number of repetitions per route.')

    # agent-related options
    parser.add_argument("-a", "--agent", type=str,
                        help="Path to Agent's py file to evaluate", required=True)
    parser.add_argument("--agent-config", type=str,
                        help="Path to Agent's configuration file", default="")

    parser.add_argument("--track", type=str, default='SENSORS',
                        help="Participation track: SENSORS, MAP")
    parser.add_argument('--resume', type=bool, default=False,
                        help='Resume execution from last checkpoint?')
    parser.add_argument("--checkpoint", type=str, default='./simulation_results.json',
                        help="Path to checkpoint used for saving statistics and resuming")
    parser.add_argument("--debug-checkpoint", type=str, default='./live_results.txt',
                        help="Path to checkpoint used for saving live results")

    arguments = parser.parse_args()

    statistics_manager = StatisticsManager(arguments.checkpoint, arguments.debug_checkpoint)
    leaderboard_evaluator = LeaderboardEvaluator(arguments, statistics_manager)
    crashed = leaderboard_evaluator.run(arguments)

    del leaderboard_evaluator
    # 在程序退出前保存
    if os.environ.get("GHOST_MODE") == "DETECT" and DETECTED_GHOSTS:
        with open("ghost_blacklist.json", "w") as f:
            json.dump(list(DETECTED_GHOSTS), f)
        print(f"💾 黑名单已保存至 ghost_blacklist.json")
    if crashed:
        sys.exit(-1)
    else:
        sys.exit(0)

if __name__ == '__main__':
    main()
