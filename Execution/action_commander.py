#!/usr/bin/env python3
"""
Action Commander - Integrated Robot Control System
Reads JSON command files and executes SCARA, DAKEN, Servo, and Gripper interfaces in sequence.
"""


import json
import logging
import time
import os
import sys
import math
from typing import Dict, List, Any, Optional, Union, Tuple
from pathlib import Path
import threading
import time


# Force UTF-8 encoding (for output in Docker environment)
import io
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')


# Logging setup (must be configured before importing settings manager)
# Use StreamHandler with explicit UTF-8 encoding
class UTF8StreamHandler(logging.StreamHandler):
    """StreamHandler that guarantees UTF-8 encoding"""
    def __init__(self, stream=None):
        super().__init__(stream)
        if stream and hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    

    def emit(self, record):
        """Output with UTF-8 encoding"""
        try:
            msg = self.format(record)
            if isinstance(msg, str):
                # Already a string, write as-is
                stream = self.stream
                stream.write(msg + self.terminator)
                self.flush()
            else:
                super().emit(record)
        except (UnicodeEncodeError, UnicodeDecodeError):
            # Fall back to default handler on encoding error
            super().emit(record)
        except Exception:
            self.handleError(record)


# Create log directory (supports both Docker and local environments)
# Docker: /app/logs, Local: project_root/logs
if os.path.exists("/app"):
    log_dir = "/app/logs"  # Docker environment
else:
    # Local development: use logs directory at project root
    log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")


# Create log directory and check write permissions
log_file_enabled = False
try:
    os.makedirs(log_dir, exist_ok=True)
    if os.access(log_dir, os.W_OK):
        # Attempt to write a test file
        test_file = os.path.join(log_dir, '.write_test')
        try:
            with open(test_file, 'w') as f:
                f.write('test')
            os.remove(test_file)
            log_file_enabled = True
        except (PermissionError, OSError):
            pass
except (PermissionError, OSError):
    pass


# Configure logging (add FileHandler only when write permission is available)
# Use direct handler addition since basicConfig may have already been called
from logging.handlers import RotatingFileHandler
import datetime


class KSTFormatter(logging.Formatter):
    """Formatter using Korean Standard Time (KST, UTC+9)"""
    def formatTime(self, record, datefmt=None):
        utc_time = datetime.datetime.utcfromtimestamp(record.created)
        kst_time = utc_time + datetime.timedelta(hours=9)
        if datefmt:
            return kst_time.strftime(datefmt)
        return kst_time.strftime('%Y-%m-%d %H:%M:%S')


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


# Add handlers only if none exist
if not logger.handlers:
    # Add file handler only when write permission is available
    if log_file_enabled:
        try:
            file_handler = RotatingFileHandler(
                os.path.join(log_dir, 'action_commander.log'),
                maxBytes=5 * 1024 * 1024, # 5MB
                backupCount=5,  # Maximum 5 backup files (25MB total)
                encoding='utf-8'
            )
            file_handler.setFormatter(KSTFormatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s', '%Y-%m-%d %H:%M:%S'))
            logger.addHandler(file_handler)
        except (PermissionError, OSError):
            pass


# Import settings manager (optional)
try:
    # Import robot_constants_manager from parent directory
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from robot_constants_manager import RobotConstantsManager
    HAS_CONFIG_MANAGER = True
except ImportError:
    HAS_CONFIG_MANAGER = False
    logger.warning(" Cannot import configuration manager. Using defaults.")


# i18n import (optional)
try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from i18n import tr
    HAS_I18N = True
except ImportError:
    HAS_I18N = False
    # Use default function if i18n is unavailable
    def tr(key, **kwargs):
        # Return key as-is (English)
        return key.format(**kwargs) if kwargs else key


# Import robot interfaces
from ScaraInterface import ScaraInterface, Gripper
from DakenInterface import DakenInterface
from ServoInterface import ServoInterface
from jig_controller import JigController
from connection_manager import get_connection_manager




class CommandParser:
    """
    Class for parsing and validating JSON command files.
    """
    

    def __init__(self, json_file_path: Optional[str] = None):
        """
        Initialize the command parser.
        

        Args:
            json_file_path (Optional[str]): Path to the JSON command file (None skips file loading)
        """
        self.json_file_path = Path(json_file_path) if json_file_path else None
        self.commands: List[Dict[str, Any]] = []
        

    def load_commands(self) -> bool:
        """
        Load commands from the JSON file.
        

        Returns:
            bool: True if loaded successfully (returns True with empty list if file not found)
        """
        try:
            # Skip file loading if json_file_path is None
            if self.json_file_path is None:
                logger.info(" JSON file path not specified. Starting with empty command list.")
                self.commands = []
                return True
            

            if not self.json_file_path.exists():
                logger.warning(f" JSON file not found: {self.json_file_path}. Starting with empty command list.")
                self.commands = []
                return True
            

            # Loading JSON file
            logger.info(f" [DEBUG] Loading JSON file: {self.json_file_path}")
            # JSON file absolute path
            logger.info(f" [DEBUG] JSON file absolute path: {self.json_file_path.resolve()}")
                

            with open(self.json_file_path, 'r', encoding='utf-8') as f:
                self.commands = json.load(f)
            

            # Debug: verify parameters of move_end_effector commands
            for i, cmd in enumerate(self.commands):
                if (cmd.get('function') == 'ScaraInterface.move_end_effector' and
                    cmd.get('type') == 'equip' and
                    cmd.get('action') == 'move_xy_position'):
                    params = cmd.get('parameters', {})
                    # Check parameters for command #{i}
                    logger.info(f" [DEBUG] CommandParser.load_commands - Checking parameters for command #{i}:")
                    # parameters type
                    logger.info(f" - parameters type: {type(params)}")
                    # parameters keys
                    logger.info(f" - parameters keys: {list(params.keys()) if isinstance(params, dict) else 'N/A'}")
                    # full parameters
                    logger.info(f" - parameters full: {params}")
                    logger.info(f" - calibration_angles: {params.get('calibration_angles')}")
                    logger.info(f" - tool_name: {params.get('tool_name')}")
                    logger.info(f" - grid_row: {params.get('grid_row')}")
                    logger.info(f" - grid_col: {params.get('grid_col')}")
                    break  # Check only the first occurrence
                

            logger.info(f" Loaded {len(self.commands)} commands")
            return True
            

        except json.JSONDecodeError as e:
            logger.error(f" JSON parsing error: {e}")
            return False
        except Exception as e:
            logger.error(f" File load error: {e}")
            return False
    

    def validate_command(self, command: Dict[str, Any]) -> bool:
        """
        Validate an individual command.
        

        Args:
            command (Dict): Command to validate
            

        Returns:
            bool: Validation result
        """
        # 'type' field is required
        if 'type' not in command:
            logger.warning(f" Required field 'type' is missing: {command}")
            return False
        

        # Either 'name' or 'action' field must be present
        if 'name' not in command and 'action' not in command:
            logger.warning(f" Required field 'name' or 'action' is missing: {command}")
            return False
                

        return True
    

    def get_commands_by_type(self, command_type: str) -> List[Dict[str, Any]]:
        """
        Filter commands by type.
        

        Args:
            command_type (str): Command type to filter
            

        Returns:
            List[Dict]: List of commands of the specified type
        """
        return [cmd for cmd in self.commands if cmd.get('type') == command_type]




class MeasurementInterface:
    """
    Measurement system interface class.
    Manages JIG and electrochemistry measurement.
    """
    

    def __init__(self, gui_callback=None):
        self.measurement_system = None
        self.is_connected = False
        self.gui_callback = gui_callback  # Store GUI callback
        

    def connect(self) -> bool:
        """Connect measurement system (reuse existing connection if available)."""
        try:
            # Reuse if already connected and valid
            if self.is_connected and self.measurement_system:
                if self._is_connection_valid():
                    # Reusing existing Measurement system connection
                    logger.info(" Reusing existing Measurement system connection")
                    return True
                else:
                    logger.warning(" Existing connection invalid, attempting new connection")
                    self.is_connected = False
                    self.measurement_system = None
            

            # Create new connection
            from measurement_system import MeasurementSystem
            

            self.measurement_system = MeasurementSystem(
                debug=False,
                gui_callback=self.gui_callback  # Pass GUI callback
            )
            

            if self.measurement_system.initialize():
                self.is_connected = True
                # Measurement system initialization completed
                logger.info(" Measurement system initialization completed")
                return True
            else:
                logger.warning(" Measurement system initialization failed")
                return False
        except Exception as e:
            logger.error(f" Measurement system connection error: {e}")
            return False
    

    def _is_connection_valid(self) -> bool:
        """Check if the connection is still valid."""
        try:
            if not self.measurement_system:
                return False
            

            # Check connection state
            if hasattr(self.measurement_system, 'is_connected'):
                return self.measurement_system.is_connected()
            

            # Assume valid by default
            return True
        except Exception as e:
            logger.warning(f"Connection validity check failed: {e}")
            return False
    

    def start_measurement(self, measurement_type: str, sample_position: int = 0,
                         measurement_params: Dict = None) -> bool:
        """Start measurement - uses run_single_measurement."""
        if not self.is_connected or not self.measurement_system:
            logger.error(" Measurement system is not connected")
            return False
            

        try:
            result = self.measurement_system.run_single_measurement(
                measurement_type=measurement_type,
                sample_position=sample_position,
                measurement_params=measurement_params
            )
            

            return result['success']
            

        except Exception as e:
            logger.error(f" Measurement execution error: {e}")
            return False
    

    def start_measurement_realtime(self, measurement_type: str, sample_position: int = 0,
                                   measurement_params: Dict = None,
                                   realtime_plotter=None) -> bool:
        """
        Start measurement with realtime graph update
        

        Args:
            measurement_type: Measurement type
            sample_position: Sample position index
            measurement_params: Measurement parameters
            realtime_plotter: RealtimeMeasurementPlotter instance (optional)
        

        Returns:
            bool: Whether measurement succeeded
        """
        if not self.is_connected or not self.measurement_system:
            logger.error(" Measurement system is not connected")
            return False
        

        try:
            result = self.measurement_system.run_single_measurement_realtime(
                measurement_type=measurement_type,
                sample_position=sample_position,
                measurement_params=measurement_params,
                realtime_plotter=realtime_plotter
            )
            

            return result.get('success', False)
            

        except Exception as e:
            logger.error(f" Realtime measurement execution error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    

    def disconnect(self):
        """Disconnect measurement system."""
        try:
            if self.measurement_system:
                self.measurement_system.shutdown()
            self.is_connected = False
            # Measurement system connection released
            logger.info(" Measurement system connection released")
        except Exception as e:
            logger.error(f" Measurement system disconnection error: {e}")




class InterfaceManager:
    """
    Class that manages all robot interfaces.
    """
    

    def __init__(self, gui_callback=None):
        """Initialize the interface manager."""
        self.scara: Optional[ScaraInterface] = None
        self.daken: Optional[DakenInterface] = None
        self.servo: Optional[ServoInterface] = None
        self.gripper: Optional[Gripper] = None
        self.measurement: Optional[MeasurementInterface] = None
        self.jig: Optional[JigController] = None
        self.gui_callback = gui_callback  # Store GUI callback
        

        # Initialize connection manager
        self.connection_manager = get_connection_manager()
        self._register_connection_factories()
        

        self.connected_interfaces = {
            'scara': False,
            'daken': False,
            'servo': False,
            'gripper': False,
            'measurement': False,
            'jig': False
        }
    

    def _register_connection_factories(self):
        """Register connection factory functions (with detailed logging)."""
        # Factory function for Measurement connection
        def create_measurement_connection(port=None, **kwargs):
            # Calling Measurement connection creation function
            logger.info(f" Calling Measurement connection creation function (port: {port})")
            

            try:
                from measurement_system import MeasurementSystem
                # MeasurementSystem module loaded
                logger.info(f" MeasurementSystem module loaded")
                

                measurement_system = MeasurementSystem(
                    ec_port=port,
                    debug=False,
                    gui_callback=self.gui_callback
                )
                # MeasurementSystem object created
                logger.info(f" MeasurementSystem object created")
                

                # Starting MeasurementSystem initialization
                logger.info(f" Starting MeasurementSystem initialization...")
                if measurement_system.initialize():
                    # MeasurementSystem initialization successful
                    logger.info(f" MeasurementSystem initialization successful")
                    return measurement_system
                else:
                    logger.error(f" MeasurementSystem initialization failed")
                    return None
                    

            except Exception as e:
                logger.error(f" Measurement connection creation error: {e}")
                return None
        

        # Factory function for JIG connection
        def create_jig_connection(port='/dev/ttyACM1', **kwargs):
            # Calling JIG connection creation function
            logger.info(f" Calling JIG connection creation function (port: {port})")
            

            try:
                jig = JigController(
                    port=port,
                    slave_id=1,
                    baudrate=115200,
                    debug=False
                )
                # JigController object created
                logger.info(f" JigController object created")
                

                # Starting JigController connection
                logger.info(f" Starting JigController connection...")
                if jig.connect():
                    # JigController connection successful
                    logger.info(f" JigController connection successful")
                    # Starting JigController initialization
                    logger.info(f" Starting JigController initialization...")
                    jig.init()
                    # JigController initialization completed
                    logger.info(f" JigController initialization completed")
                    return jig
                else:
                    logger.error(f" JigController connection failed")
                    return None
                    

            except Exception as e:
                logger.error(f" JIG connection creation error: {e}")
                return None
        

        # Register factory functions
        # Starting connection factory registration
        logger.info(f" Starting connection creation function registration...")
        self.connection_manager.register_connection_factory('measurement', create_measurement_connection)
        self.connection_manager.register_connection_factory('jig', create_jig_connection)
        # Connection factory registration completed
        logger.info(f" Connection creation function registration completed")
    

    def connect_all(self) -> bool:
        """
        Connect all interfaces.
        

        Returns:
            bool: True if all connections succeeded
        """
        # Initialize robot interfaces
        logger.info(" Initializing robot interfaces...")
        

        success_count = 0
        total_interfaces = 6
        

        # Connect SCARA interface
        try:
            self.scara = ScaraInterface()
            if self.scara.connect():
                self.scara.initialize()
                self.connected_interfaces['scara'] = True
                success_count += 1
                # SCARA interface connection successful
                logger.info(" SCARA interface connection successful")
            else:
                logger.warning(f" {tr('message.scara.connection_failed')}")
        except Exception as e:
            logger.error(f" SCARA connection error: {e}")
        

        # Connect DAKEN interface
        try:
            self.daken = DakenInterface(debug=True)  # Enable debug mode
            if self.daken.connect():
                # Run DAKEN initialization
                init_result = self.daken.initialize()
                if init_result == "OK":
                    self.connected_interfaces['daken'] = True
                    success_count += 1
                    # DAKEN interface connection and initialization successful
                    logger.info(" DAKEN interface connection and initialization successful")
                else:
                    logger.warning(f" DAKEN initialization failed: {init_result}")
                    self.daken.disconnect()
            else:
                logger.warning(" DAKEN interface connection failed")
        except Exception as e:
            logger.error(f" DAKEN connection error: {e}")
            if hasattr(self, 'daken') and self.daken:
                try:
                    self.daken.disconnect()
                except:
                    pass
        

        # Connect Servo interface
        try:
            self.servo = ServoInterface()
            if self.servo.connect():
                self.connected_interfaces['servo'] = True
                success_count += 1
                # Servo interface connection successful
                logger.info(" Servo interface connection successful")
            else:
                logger.warning(" Servo interface connection failed")
        except Exception as e:
            logger.error(f" Servo connection error: {e}")
        

        # Connect Gripper interface (included in SCARA)
        if self.connected_interfaces['scara']:
            try:
                # SCARA robot must be initialized first
                if not self.scara.initialized:
                    # Initializing SCARA robot
                    logger.info(" Initializing SCARA robot...")
                    if self.scara.initialize():
                        # SCARA robot initialization completed
                        logger.info(" SCARA robot initialization completed")
                        

                        # Unlock position
                        if self.scara.unlock_position():
                            # SCARA position unlock completed
                            logger.info(" SCARA position unlock completed")
                        else:
                            logger.warning(" SCARA position unlock failed")
                    else:
                        logger.error(" SCARA robot initialization failed")
                        return success_count > 0
                else:
                    # SCARA robot is already initialized
                    logger.info(" SCARA robot is already initialized")
                    # Also verify position unlock if already initialized
                    if not self.scara.unlock_position():
                        logger.warning(" SCARA position unlock failed")
                

                # Create and initialize gripper object
                # Initializing gripper
                logger.info(" Initializing gripper...")
                self.gripper = self.scara.get_gripper()
                if self.gripper.initialize():
                    self.connected_interfaces['gripper'] = True
                    success_count += 1
                    logger.info(" Gripper interface connection successful")
                    

                    # Check gripper state
                    try:
                        current_distance = self.gripper.get_clamping_distance()
                        current_angle = self.gripper.get_rotation_angle()
                        # Gripper initial state - clamping distance, rotation angle
                        logger.info(f" Gripper initial state - Clamping distance: {current_distance}mm, Rotation angle: {current_angle}°")
                    except Exception as e:
                        logger.warning(f" Gripper status check failed: {e}")
                else:
                    logger.warning(" Gripper interface connection failed")
            except Exception as e:
                logger.error(f" Gripper connection error: {e}")
        

        # Connect Measurement interface (via ConnectionManager)
        logger.info(" [4/6] Starting Measurement interface connection...")
        try:
            measurement_system = self.connection_manager.get_or_create_connection(
                'measurement',
                port='/dev/ttyUSB0'
            )
            if measurement_system:
                # Create MeasurementInterface wrapper
                self.measurement = MeasurementInterface(gui_callback=self.gui_callback)
                self.measurement.measurement_system = measurement_system
                self.measurement.is_connected = True
                

                self.connected_interfaces['measurement'] = True
                success_count += 1
                logger.info(" [4/6] Measurement interface connection successful")
            else:
                logger.warning(" [4/6] Measurement interface connection failed")
        except Exception as e:
            logger.error(f" [4/6] Measurement connection error: {e}")
        

        # Connect JIG interface (via ConnectionManager)
        logger.info(" [5/6] Starting JIG interface connection...")
        try:
            jig_controller = self.connection_manager.get_or_create_connection(
                'jig',
                port='/dev/ttyACM1'
            )
            if jig_controller:
                self.jig = jig_controller
                self.connected_interfaces['jig'] = True
                success_count += 1
                logger.info(" [5/6] JIG interface connection successful")
            else:
                logger.warning(" [5/6] JIG interface connection failed")
        except Exception as e:
            logger.error(f" [5/6] JIG connection error: {e}")
        

        logger.info(f" Connection result: {success_count}/{total_interfaces} interfaces connected")
        return success_count > 0
    

    def disconnect_all(self):
        """Disconnect all interfaces."""
        logger.info(" Disconnecting all interfaces...")
        

        if self.scara and self.connected_interfaces['scara']:
            try:
                #self.scara.disconnect()
                logger.info(" SCARA connection released")
            except Exception as e:
                logger.error(f" SCARA disconnection error: {e}")
        

        if self.daken and self.connected_interfaces['daken']:
            try:
                # Check DAKEN status before disconnecting
                logger.info(" Checking DAKEN status...")
                try:
                    status = self.daken.read_running_status()
                    if status:
                        logger.info(f" DAKEN current status: {status}")
                except:
                    pass
                

                self.daken.disconnect()
                logger.info(" DAKEN connection released")
            except Exception as e:
                logger.error(f" DAKEN disconnection error: {e}")
        

        if self.servo and self.connected_interfaces['servo']:
            try:
                self.servo.disconnect()
                logger.info(" Servo connection released")
            except Exception as e:
                logger.error(f" Servo disconnection error: {e}")
        

        # Measurement and JIG are managed by ConnectionManager; no separate release needed
        # ConnectionManager handles them automatically
        

        # Reset connection state
        self.connected_interfaces = {
            'scara': False,
            'daken': False,
            'servo': False,
            'gripper': False,
            'measurement': False,
            'jig': False
        }
        

        logger.info(" All interfaces disconnected")




class CommandExecutor:
    """
    Class that executes individual commands.
    """
    

    def __init__(self, interface_manager: InterfaceManager, tube_interface=None, gui_callback=None, action_commander=None, config_manager=None, mea_stack_manager=None):
        """
        Initialize the command executor.
        

        Args:
            interface_manager (InterfaceManager): Interface manager instance
            tube_interface: Tube Interface instance
            gui_callback: GUI callback function
            action_commander: ActionCommander instance (for pause/stop checks)
            config_manager: Settings manager instance
            mea_stack_manager: MEA Stack Manager instance (optional)
        """
        self.interface_manager = interface_manager
        self.tube_interface = tube_interface  # Tube Interface
        self.gui_callback = gui_callback  # GUI callback
        self.action_commander = action_commander  # ActionCommander reference
        self.config_manager = config_manager  # Settings manager
        

        # Initialize MEA Stack Manager (optional)
        if mea_stack_manager:
            self.stack_manager = mea_stack_manager
        else:
            try:
                import sys
                import os
                # Add project root path
                project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                if project_root not in sys.path:
                    sys.path.insert(0, project_root)
                from models.mea_stack_manager import MEAStackManager
                self.stack_manager = MEAStackManager()
            except ImportError:
                self.stack_manager = None
        

        # GUI update callback (for MEA stack state updates)
        self.gui_update_callback = None
        

        # Store current pick/place action context (for quantity management on gripper close/open)
        self.current_pick_context = None # {'action': 'pick', 'location': 'mea1', 'tool_name': 'mea1'}
        self.current_place_context = None # {'action': 'place', 'location': 'mea1', 'tool_name': 'mea1'}
        

        # Track currently active interfaces (for status display)
        self.current_active_interfaces = set()  # Set of currently active interfaces
        

        # Track source_id of last take action (to decide whether to dispense 30uL in dispose action)
        self.last_take_source_id = None
        

        # Load constant values from settings (helper method)
        self._load_constants()
    

    def _notify_gui_update(self, location: str):
        """Notify GUI to update."""
        if self.gui_update_callback:
            try:
                count = self.stack_manager.get_stack_count(location) if self.stack_manager else 0
                self.gui_update_callback(location, count)
            except Exception as e:
                logger.warning(f" GUI update callback error: {e}")
    

    def set_gui_update_callback(self, callback):
        """Set GUI update callback."""
        self.gui_update_callback = callback
    

    def get_current_active_interfaces(self) -> set:
        """Return the set of currently active interfaces."""
        return self.current_active_interfaces.copy()
    

    def _load_constants(self):
        """Load constant values from settings."""
        if self.config_manager:
            # Speed-related
            self.move_offset_low_speed = self.config_manager.get("speed", "move_offset_low_speed") or 5
            self.tip_equip_z_axis_speed = self.config_manager.get("speed", "tip_equip_z_axis_speed") or 10
            self.pre_surface_detection_z_axis_speed = self.config_manager.get("speed", "pre_surface_detection_z_axis_speed") or 10
            self.mea_spit_diagonal_move_speed = self.config_manager.get("speed", "mea_spit_diagonal_move_speed") or 5.0
            self.mea_storage_internal_speed = self.config_manager.get("speed", "mea_storage_internal_speed") or 10.0
            self.mea_apply_z_offset = self.config_manager.get("offset_distance", "mea_apply_z_offset") or 11.5
            self.surface_detection_descent_speed = self.config_manager.get("speed", "surface_detection_descent_speed") or 0.5
            self.surface_detection_rise_speed = self.config_manager.get("speed", "surface_detection_rise_speed") or 10
            self.surface_detection_return_speed = self.config_manager.get("speed", "surface_detection_return_speed") or 10
            self.initial_position_move_to_top_speed = self.config_manager.get("speed", "initial_position_move_to_top_speed") or 50
            self.initial_position_speed = self.config_manager.get("speed", "initial_position_speed") or 50
            

            # Retry-related
            self.tip_equip_max_retries = self.config_manager.get("retry", "tip_equip_max_retries") or 3
            self.retry_delay = self.config_manager.get("retry", "retry_delay") or 1.0
            

            # Offset/distance-related
            self.tip_equip_z_offset = self.config_manager.get("offset_distance", "tip_equip_z_offset") or 7
            self.descent_start_check_distance = self.config_manager.get("offset_distance", "descent_start_check_distance") or 0.5
            self.dynamic_surface_offset = self.config_manager.get("offset_distance", "dynamic_surface_offset") or 5.0
            self.surface_height_margin = self.config_manager.get("offset_distance", "surface_height_margin") or 2
            self.surface_detection_rise_distance = self.config_manager.get("offset_distance", "surface_detection_rise_distance") or 1.7
            self.surface_detection_return_distance = self.config_manager.get("offset_distance", "surface_detection_return_distance") or 10
            self.surface_detection_descent_step = self.config_manager.get("offset_distance", "surface_detection_descent_step") or -0.2
            self.align_distance = self.config_manager.get("offset_distance", "align_distance") or 2.5
            self.mea_spit_90degree_move_distance = self.config_manager.get("offset_distance", "mea_spit_90degree_move_distance") or 2.0
            self.aspiration_post_z_offset = self.config_manager.get("offset_distance", "aspiration_post_z_offset") or 1.0
            self.aspiration_post_x_offset = self.config_manager.get("offset_distance", "aspiration_post_x_offset") or 2.0
            

            # Wait time-related
            self.liquid_spit_pre_wait = self.config_manager.get("wait_time", "liquid_spit_pre_wait") or 1.0
            self.liquid_spit_post_wait = self.config_manager.get("wait_time", "liquid_spit_post_wait") or 0.2
            self.tip_equip_wait_time = self.config_manager.get("wait_time", "tip_equip_wait_time") or 0.5
            self.general_check_interval = self.config_manager.get("wait_time", "general_check_interval") or 0.1
            self.surface_detection_check_interval = self.config_manager.get("wait_time", "surface_detection_check_interval") or 0.1
            

            # Timeout-related
            self.movement_completion_timeout = self.config_manager.get("timeout", "movement_completion_timeout") or 2.0
            self.scara_descent_wait_timeout = self.config_manager.get("timeout", "scara_descent_wait_timeout") or 30.0
            self.surface_detection_timeout = self.config_manager.get("timeout", "surface_detection_timeout") or 30.0
            

            # Default values
            self.aspiration_amount_default = self.config_manager.get("defaults", "aspiration_amount_default") or 100
            self.spit_amount_default = self.config_manager.get("defaults", "spit_amount_default") or 50
        else:
            # Default values (no config manager)
            self.move_offset_low_speed = 5
            self.tip_equip_z_axis_speed = 10
            self.pre_surface_detection_z_axis_speed = 10
            self.mea_spit_diagonal_move_speed = 5.0
            self.mea_storage_internal_speed = 10.0
            self.mea_apply_z_offset = 11.5
            self.surface_detection_descent_speed = 0.5
            self.surface_detection_rise_speed = 10
            self.surface_detection_return_speed = 10
            self.initial_position_move_to_top_speed = 50
            self.initial_position_speed = 50
            self.tip_equip_max_retries = 3
            self.retry_delay = 1.0
            self.tip_equip_z_offset = 7
            self.descent_start_check_distance = 0.5
            self.dynamic_surface_offset = 5.0
            self.surface_height_margin = 2
            self.surface_detection_rise_distance = 1.7
            self.surface_detection_return_distance = 10
            self.surface_detection_descent_step = -0.2
            self.align_distance = 2.5
            self.mea_spit_90degree_move_distance = 2.0
            self.aspiration_post_z_offset = 1.0
            self.aspiration_post_x_offset = 2.0
            self.liquid_spit_pre_wait = 1.0
            self.liquid_spit_post_wait = 0.2
            self.tip_equip_wait_time = 0.5
            self.general_check_interval = 0.1
            self.surface_detection_check_interval = 0.1
            self.movement_completion_timeout = 2.0
            self.scara_descent_wait_timeout = 30.0
            self.surface_detection_timeout = 30.0
            self.aspiration_amount_default = 100
            self.spit_amount_default = 50
        

        # Function mapping table: maps command function names to handler methods
        self.function_mapping = {
            'ScaraInterface.move_end_effector': self._execute_scara_move_end_effector,
            'ScaraInterface.movel_xyz': self._execute_scara_movel,
            'ScaraInterface.move_to_top': self._execute_scara_move_to_top,
            'ScaraInterface.move_offset': self._execute_scara_move_offset,
            'DakenInterface.check_tip': self._execute_daken_check_tip,
            'DakenInterface.aspirate_liquid': self._execute_daken_aspirate,
            'DakenInterface.spit_liquid': self._execute_daken_spit,
            'DakenInterface.initialize': self._execute_daken_initialize,
            'DakenInterface.aspirate_first_air': self._execute_daken_aspirate_first_air,
            'DakenInterface.reject_tip': self._execute_daken_reject_tip,
            'DakenInterface.eject_tip': self._execute_daken_reject_tip,  # eject_tip handled same as reject_tip
            'ServorInterface.move_to_angle': self._execute_servo_move_angle,
            'ScaraInterface.gripper.open': self._execute_gripper_open,
            'ScaraInterface.gripper.close': self._execute_gripper_close,
            'MeasurementInterface.start_measurement': self._execute_measurement_start,
            'CommandExecutor._execute_tip_equip_with_retry': self._execute_tip_equip_with_retry,
            'JigController.open': self._execute_jig_open,
            'JigController.close': self._execute_jig_close,
            'time.sleep': self._execute_time_sleep
        }
    

    def execute_command(self, command: Dict[str, Any]) -> bool:
        """
        Execute an individual command.
        

        Args:
            command (Dict): Command to execute
            

        Returns:
            bool: True if execution succeeded
        """
        # Use 'action' field if 'name' field is absent
        command_name = command.get('name') or command.get('action', 'Unknown')
        command_type = command.get('type', 'unknown')
        function_name = command.get('function', '')
        parameters = command.get('parameters', {})
        description = command.get('description', '')
        

        # Debug: verify parameters for move_end_effector commands
        if function_name == 'ScaraInterface.move_end_effector':
            # Check parameters
            logger.info(f" [DEBUG] execute_command - Checking parameters:")
            # parameters type
            logger.info(f" - parameters type: {type(parameters)}")
            # parameters keys
            logger.info(f" - parameters keys: {list(parameters.keys()) if isinstance(parameters, dict) else 'N/A'}")
            logger.info(f" - calibration_angles: {parameters.get('calibration_angles') if isinstance(parameters, dict) else 'N/A'}")
            logger.info(f" - tool_name: {parameters.get('tool_name') if isinstance(parameters, dict) else 'N/A'}")
            logger.info(f" - grid_row: {parameters.get('grid_row') if isinstance(parameters, dict) else 'N/A'}")
            logger.info(f" - grid_col: {parameters.get('grid_col') if isinstance(parameters, dict) else 'N/A'}")
        

        # Log command execution
        logger.info(f" Executing command: [{command_type}] {command_name}")
        if description:
            # Description
            logger.info(f" Description: {description}")
        

        # Protocol info and process start/end only require logging
        if command_type in ['protocol_info', 'process_start', 'process_end']:
            logger.info(f" {command_type}: {command_name}")
            return True
        

        # Execute mapped function
        if function_name in self.function_mapping:
            try:
                # Debug: detect move_offset command
                if function_name == 'ScaraInterface.move_offset':
                    # move_offset command detected
                    logger.info(f" [DEBUG] move_offset command detected: function_name={function_name}, parameters={parameters}")
                

                # Pass command type to spit_liquid for 2mm movement detection
                if function_name == 'DakenInterface.spit_liquid':
                    if isinstance(parameters, dict) and 'type' not in parameters:
                        parameters['type'] = command_type
                        logger.info(f" [DEBUG] Added 'type' to parameters: {command_type}")
                

                # Pass action and type info to move_end_effector for move_z_position detection
                if function_name == 'ScaraInterface.move_end_effector':
                    parameters['action'] = command_name  # Attach action info to parameters
                    parameters['type'] = command_type  # Attach type info for stack_count calculation
                

                # Pass type info to move_to_top for speed adjustment after place action
                if function_name == 'ScaraInterface.move_to_top':
                    parameters['type'] = command_type  # Attach type info
                

                result = self.function_mapping[function_name](parameters)
                # Convert result to bool (handles None, dict, etc.)
                success = bool(result) if result is not None else False
                if success:
                    # Command completed
                    logger.info(f" Command completed: {command_name}")
                else:
                    logger.error(f" Command failed: {command_name}")
                return success
            except Exception as e:
                logger.error(f" Command execution error [{command_name}]: {e}")
                return False
        else:
            logger.warning(f" Unsupported function: {function_name}")
            logger.warning(f" [DEBUG] function_name={function_name}, available functions={list(self.function_mapping.keys())}")
            return False
    

    def _execute_scara_move_end_effector(self, parameters: Dict[str, Any]) -> bool:
        """Execute SCARA move_end_effector command."""
        if not self.interface_manager.connected_interfaces['scara']:
            logger.error(" SCARA interface is not connected")
            return False
        

        try:
            end_effector = parameters.get('end_effector', 'pipette')
            xyz = parameters.get('xyz', [0, 0, 0])
            tip = parameters.get('tip', False)
            speed = float(parameters.get('speed', 100))
            

            # For move_z_position action: keep current angles and change only Z
            action = parameters.get('action')  # action info passed from command
            if action == 'move_z_position':
                logger.info(f" [DEBUG] move_z_position detected: Moving Z-axis only (maintaining current angles)")
                logger.info(f" - xyz parameter: {xyz}")
                logger.info(f" - target Z (xyz[2]): {xyz[2]:.2f}mm")
                try:
                    # For MEA locations: recalculate height considering stack_count
                    tool_name = parameters.get('tool_name')
                    # Retrieve tool_name from previous command context if not provided
                    if not tool_name:
                        if hasattr(self, 'last_tool_name') and self.last_tool_name:
                            tool_name = self.last_tool_name
                            logger.info(f" [move_z_position] No tool_name, using last_tool_name: {tool_name}")
                    command_type = parameters.get('type')  # 'pick' or 'place' from command type field
                    

                    # Process only for pick or place command types
                    parent_action = command_type if command_type in ['pick', 'place'] else None
                    

                    # Process MEA locations the same way as gripper calibration
                    if tool_name and 'mea' in tool_name.lower() and parent_action in ['pick', 'place']:
                        location = tool_name.lower()
                        

                        # Check height_calculator and stack_manager
                        if hasattr(self, 'stack_manager') and self.stack_manager:
                            # Dynamically create height_calculator if not present
                            if not hasattr(self, 'height_calculator') or self.height_calculator is None:
                                try:
                                    import sys
                                    import os
                                    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                                    if project_root not in sys.path:
                                        sys.path.insert(0, project_root)
                                    from utils.mea_height_calculator import MEAHeightCalculator
                                    self.height_calculator = MEAHeightCalculator(self.stack_manager)
                                    logger.info(" MEAHeightCalculator dynamically created")
                                except Exception as e:
                                    logger.warning(f" MEAHeightCalculator creation failed: {e}")
                                    self.height_calculator = None
                            

                            if self.height_calculator:
                                logger.info(f" [move_z_position] MEA location detected: {location}, parent_action: {parent_action}")
                                

                                if parent_action == 'pick':
                                    # Pick: if stack_count is 0, force it to 1 (height when 1 item exists)
                                    current_stack_count = self.stack_manager.get_stack_count(location)
                                    logger.info(f" - Current stack_count: {current_stack_count}")
                                    

                                    # Temporarily set stack_count to 1 for height calculation (save original)
                                    original_stack_count = current_stack_count
                                    if current_stack_count == 0:
                                        self.stack_manager.set_stack_count(location, 1)
                                        logger.info(f" - Setting stack_count from 0 → 1 for Pick calculation (height when 1 item exists)")
                                    

                                    # Recalculate height
                                    pick_height = self.height_calculator.calculate_pick_height(location)
                                    if pick_height is not None:
                                        # pick_height is already the Z coordinate of the end effector tip
                                        xyz[2] = pick_height
                                        logger.info(f" - Recalculated height considering stack_count: {pick_height:.2f}mm")
                                    

                                    # Restore original stack_count (actual pick is handled by gripper close)
                                    if original_stack_count == 0:
                                        self.stack_manager.set_stack_count(location, 0)
                                        logger.info(f" - Restored stack_count to original value ({original_stack_count}) after calculation")
                                

                                elif parent_action == 'place':
                                    # Place: recalculate height using current stack_count
                                    current_stack_count = self.stack_manager.get_stack_count(location)
                                    logger.info(f" - Current stack_count: {current_stack_count}")
                                    

                                    # Recalculate height
                                    place_height = self.height_calculator.calculate_place_height(location)
                                    if place_height is not None:
                                        # place_height is already the Z coordinate of the end effector tip
                                        xyz[2] = place_height
                                        logger.info(f" - Recalculated height considering stack_count: {place_height:.2f}mm")
                    

                    # Get current angles and coordinates from SCARA
                    current_pos = self.interface_manager.scara.get_current_position()
                    if current_pos:
                        current_angle1 = current_pos['angle1']
                        current_angle2 = current_pos['angle2']
                        current_robot_z = current_pos['z']  # Current robot Z coordinate
                        

                        # Get end effector offset
                        # Check current_end_effector for Angled Pipette handling
                        current_end_effector = self.interface_manager.scara.current_end_effector
                        effective_end_effector_for_offset = end_effector
                        effective_tool_name = tool_name
                        effective_with_tip = tip
                        

                        # For dispose action: ignore tool_name (moving to liq-trash)
                        command_type = parameters.get('type')
                        if command_type == 'dispose':
                            effective_tool_name = None
                            logger.info(f" [move_z_position] dispose action detected: tool_name ignored (moving to liq-trash)")
                        # Retrieve tool_name from previous command context if not provided
                        elif not effective_tool_name:
                            if hasattr(self, 'last_tool_name') and self.last_tool_name:
                                effective_tool_name = self.last_tool_name
                                logger.info(f" [move_z_position] No tool_name, using last_tool_name: {effective_tool_name}")
                        

                        # Handle mea2/mea-measure: use different end effector for take vs apply
                        # Condition: pipette end effector with tool_name mea2 or mea-measure
                        is_mea_case = self._is_angled_pipette_mode(end_effector, effective_tool_name, current_end_effector)
                        

                        if is_mea_case:
                            # Use default if effective_tool_name is still not set
                            if not effective_tool_name:
                                effective_tool_name = 'mea2'  # Default value
                                logger.info(f" [move_z_position] No tool_name, using default: {effective_tool_name}")
                            

                            # Check action (take, mix, or apply)
                            # move_z_position must check the parent action type
                            parent_action_type = parameters.get('type')  # 'take', 'mix', or 'apply'
                            # Mix action is handled the same as take action
                            is_take = (parent_action_type == 'take' or parent_action_type == 'mix')
                            

                            if is_take:
                                # Take or mix action: use Pipette with tip
                                effective_end_effector_for_offset = 'pipette'
                                effective_with_tip = True
                                action_name = 'Take' if parent_action_type == 'take' else 'Mix'
                                logger.info(f" [move_z_position] {action_name} action detected: tool_name={effective_tool_name}, Pipette with tip (with_tip={effective_with_tip})")
                            else:
                                # Apply action: use Angled Pipette
                                effective_end_effector_for_offset = 'Angled Pipette'
                                effective_with_tip = False
                                logger.info(f" [move_z_position] Apply action detected: tool_name={effective_tool_name}, Angled Pipette (with_tip={effective_with_tip})")
                        

                        ee_offset = self.interface_manager.scara.get_end_effector_offset(effective_end_effector_for_offset, effective_with_tip, effective_tool_name)
                        

                        # Calculate current end effector tip Z using forward kinematics
                        from ikine2 import inv_kinematics
                        ik_solver = inv_kinematics(dx=ee_offset['x'], dy=ee_offset['y'], dz=ee_offset['z'])
                        current_fk = ik_solver.forward_kinematics(current_angle1, current_angle2, current_robot_z)
                        current_ee_x, current_ee_y, current_ee_z = current_fk
                        

                        # Target end effector tip Z position
                        target_ee_z = xyz[2]
                        

                        # For dispose action: lower Z by 3mm to compensate IK error
                        if command_type == 'dispose':
                            dispose_z_correction = -3.0  # Lower by 3mm
                            target_ee_z = target_ee_z + dispose_z_correction
                            logger.info(f" [move_z_position] dispose action detected: applying Z correction")
                            logger.info(f" - Original target Z: {xyz[2]:.2f}mm")
                            logger.info(f" - Corrected target Z: {target_ee_z:.2f}mm (correction: {dispose_z_correction:.2f}mm)")
                        

                        # For mea2/mea-measure: apply mea_apply_z_offset for apply, mea_take_z_offset for take
                        # Take action: apply mea_take_z_offset
                        # Apply action: apply mea_apply_z_offset
                        if is_mea_case and effective_tool_name:
                            if is_take:
                                # Take action: apply mea_take_z_offset
                                mea_z_offset = self.config_manager.get("offset_distance", "mea_take_z_offset") if self.config_manager else None
                                if mea_z_offset is None:
                                    mea_z_offset = 1.0  # Default value
                                target_ee_z = target_ee_z + mea_z_offset
                                logger.info(f"[move_z_position] {effective_tool_name} (take): mea_take_z_offset={mea_z_offset:.2f}mm applied -> target_ee_z={target_ee_z:.2f}mm")
                            else:
                                # Apply action: apply mea_apply_z_offset
                                mea_z_offset = self.config_manager.get("offset_distance", "mea_apply_z_offset") if self.config_manager else None
                                if mea_z_offset is None:
                                    mea_z_offset = 2.0  # Default value
                                target_ee_z = target_ee_z + mea_z_offset
                                logger.info(f" [move_z_position] {effective_tool_name} (apply): mea_apply_z_offset={mea_z_offset:.2f}mm applied -> target_ee_z={target_ee_z:.2f}mm")
                        

                        # For mea1/mea3: use slow speed within 70mm zone from floor
                        # Calculation example:
                        # - mea1/mea3 center_coordinates.z = -385.6mm (top of first tool)
                        # - mea_height = 12.90mm
                        # - floor_z = center_coordinates.z - mea_height = -385.6 - 12.90 = -398.5mm
                        # - threshold_z = floor_z + 70 = -398.5 + 70 = -328.5mm
                        # - Zone [floor_z, threshold_z]: use speed 10; above threshold: use normal speed
                        # - Use speed 10 in this zone; use configured speed above this zone
                        # Check location (only defined in gripper pick/place actions)
                        check_location = None
                        if tool_name and 'mea' in tool_name.lower() and parent_action in ['pick', 'place']:
                            check_location = tool_name.lower()
                        elif effective_tool_name and 'mea' in effective_tool_name.lower():
                            check_location = effective_tool_name.lower()
                        

                        # Two-stage movement flag (used for all cases)
                        need_two_stage = False
                        threshold_ee_z = None
                        

                        if check_location in ['mea1', 'mea3'] and end_effector == 'gripper':
                            # Use normal speed for pick action (descending)
                            if parent_action == 'pick':
                                logger.info(f" [move_z_position] {check_location}: pick action - using normal speed (descent)")
                                logger.info(f" - Speed: {speed:.1f}mm/s (keeping current setting)")
                            else:
                                # Dynamically create height_calculator if not present
                                if not hasattr(self, 'height_calculator') or self.height_calculator is None:
                                    if hasattr(self, 'stack_manager') and self.stack_manager:
                                        try:
                                            import sys
                                            import os
                                            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                                            if project_root not in sys.path:
                                                sys.path.insert(0, project_root)
                                            from utils.mea_height_calculator import MEAHeightCalculator
                                            self.height_calculator = MEAHeightCalculator(self.stack_manager)
                                            logger.info(" MEAHeightCalculator dynamically created for speed adjustment")
                                        except Exception as e:
                                            logger.warning(f" MEAHeightCalculator creation failed: {e}")
                                            self.height_calculator = None
                                

                                if hasattr(self, 'height_calculator') and self.height_calculator:
                                    base_z = self.height_calculator.get_tool_center_z(check_location)
                                    mea_height = self.height_calculator.mea_height
                                    if base_z is not None:
                                        # Calculate floor: base_z - mea_height
                                        floor_z = base_z - mea_height
                                    # 70mm from floor = floor_z + 70
                                    threshold_z = floor_z + 70.0
                                    

                                    # Analyze movement path considering both current and target positions:
                                    # Case 1: current outside, target inside zone -> speed change before entry
                                    # Case 2: current inside, target inside zone -> slow throughout
                                    # Case 3: current inside, target outside zone -> slow until exit
                                    # Case 4: both outside zone -> normal speed
                                    

                                    current_in_range = floor_z <= current_ee_z <= threshold_z
                                    target_in_range = floor_z <= target_ee_z <= threshold_z
                                    

                                    if target_in_range and not current_in_range:
                                        # Case: current outside, target inside -> two-stage move
                                        need_two_stage = True
                                        threshold_ee_z = threshold_z
                                        logger.info(f" [move_z_position] {check_location}: two-stage move needed (zone entry)")
                                        logger.info(f" - Current position: Z={current_ee_z:.2f}mm (outside zone)")
                                        logger.info(f" - Zone boundary: Z={threshold_z:.2f}mm")
                                        logger.info(f" - Target position: Z={target_ee_z:.2f}mm (zone: {floor_z:.2f}mm ~ {threshold_z:.2f}mm)")
                                    elif target_in_range and current_in_range:
                                        # Case: both inside zone -> slow speed throughout
                                        original_speed = speed
                                        mea_storage_speed = getattr(self, 'mea_storage_internal_speed', 10.0)
                                        speed = mea_storage_speed
                                        logger.info(f" [move_z_position] {check_location}: moving inside zone (speed {speed:.1f} applied)")
                                        logger.info(f" - Current position: Z={current_ee_z:.2f}mm (inside zone)")
                                        logger.info(f" - Target position: Z={target_ee_z:.2f}mm (inside zone)")
                                        logger.info(f" - Speed adjustment: {original_speed:.1f} → {speed:.1f}mm/s")
                                    elif current_in_range and target_ee_z < floor_z:
                                        # Case: current inside, target outside(below) -> slow until zone exit
                                        original_speed = speed
                                        mea_storage_speed = getattr(self, 'mea_storage_internal_speed', 10.0)
                                        speed = mea_storage_speed
                                        logger.info(f" [move_z_position] {check_location}: starting from inside zone (speed {speed:.1f} applied)")
                                        logger.info(f" - Current position: Z={current_ee_z:.2f}mm (inside zone)")
                                        logger.info(f" - Target position: Z={target_ee_z:.2f}mm (outside zone, below)")
                                        logger.info(f" - Speed adjustment: {original_speed:.1f} → {speed:.1f}mm/s")
                                    elif target_ee_z > threshold_z:
                                        logger.info(f" [move_z_position] {check_location}: zone 70mm+ from floor (using current speed)")
                                        logger.info(f" - Current position: Z={current_ee_z:.2f}mm")
                                        logger.info(f" - Target position: Z={target_ee_z:.2f}mm > threshold_z ({threshold_z:.2f}mm)")
                                        logger.info(f" - Speed: {speed:.1f}mm/s (keeping current setting)")
                        

                        # Determine right_handed from current angle sign (to preserve current angles)
                        # angle2 >= 0: right-handed; angle2 < 0: left-handed
                        current_right_handed = (current_angle2 >= 0)
                        logger.info(f" [move_z_position] Coordinate calculation based on current angle: angle2={current_angle2:.2f}° -> {'right-handed' if current_right_handed else 'left-handed'}")
                        

                        # Two-stage movement processing
                        if need_two_stage and threshold_ee_z is not None:
                            # Stage 1: current position -> zone boundary (threshold_z) - normal speed
                            logger.info(f" [move_z_position] Stage 1: current position → zone boundary (speed: {speed:.1f}mm/s)")
                            

                            # Calculate IK for zone boundary
                            rv_threshold = ik_solver.inverse_kinematics_separated(
                                current_ee_x, current_ee_y, threshold_ee_z, right_handed=current_right_handed
                            )
                            

                            if rv_threshold is None:
                                logger.warning(f" Step 1 IK calculation failed, processing entire movement at low speed")
                                # Process entire movement at slow speed (fallback)
                                mea_storage_speed = getattr(self, 'mea_storage_internal_speed', 10.0)
                                original_speed = speed
                                speed = mea_storage_speed
                                logger.info(f" - Speed adjustment: {original_speed:.1f} → {speed:.1f}mm/s (fallback)")
                            else:
                                robot_z_threshold = max(float(rv_threshold[2]), -240)
                                

                                # Stage 1 move: to zone boundary
                                result1 = self.interface_manager.scara.move_to_angle(
                                    current_angle1,
                                    current_angle2,
                                    robot_z_threshold,
                                    0,
                                    speed=speed,  # Normal speed
                                    roughly=0,
                                    skip_gripper_rotation=True
                                )
                                

                                if not result1:
                                    logger.error(f" Step 1 movement failed")
                                    return False
                                

                                logger.info(f" [move_z_position] Stage 1 done: zone boundary reached (Z={threshold_ee_z:.2f}mm)")
                                

                                # Stage 2: zone boundary -> target at mea_storage_internal_speed
                                mea_storage_speed = getattr(self, 'mea_storage_internal_speed', 10.0)
                                logger.info(f" [move_z_position] Stage 2: zone boundary → target (speed: {mea_storage_speed:.1f}mm/s)")
                                

                                # Update current position after Stage 1
                                self.interface_manager.scara.robot.get_encoder_coor()
                                current_angle1_after = self.interface_manager.scara.robot.encoder_angle1
                                current_angle2_after = self.interface_manager.scara.robot.encoder_angle2
                                

                                # Calculate IK for target position
                                rv_target = ik_solver.inverse_kinematics_separated(
                                    current_ee_x, current_ee_y, target_ee_z, right_handed=current_right_handed
                                )
                                

                                if rv_target is None:
                                    logger.warning(f" Step 2 IK calculation failed")
                                    return False
                                

                                robot_z_target = max(float(rv_target[2]), -240)
                                

                                # Stage 2 move: to target position
                                result2 = self.interface_manager.scara.move_to_angle(
                                    current_angle1_after,
                                    current_angle2_after,
                                    robot_z_target,
                                    0,
                                    speed=mea_storage_speed,  # Slow speed
                                    roughly=0,
                                    skip_gripper_rotation=True
                                )
                                

                                if not result2:
                                    logger.error(f" Step 2 movement failed")
                                    return False
                                

                                logger.info(f" [move_z_position] Stage 2 done: target reached (Z={target_ee_z:.2f}mm)")
                                logger.info(f" - base_z (first tool top): {base_z:.2f}mm")
                                logger.info(f" - mea_height: {mea_height:.2f}mm")
                                logger.info(f" - Floor (floor_z): {floor_z:.2f}mm (base_z - mea_height)")
                                logger.info(f" - 70mm from floor (threshold_z): {threshold_z:.2f}mm (floor_z + 70)")
                                return True
                        

                        # Single-stage movement (standard logic)
                        # Use current X,Y (end effector tip) and target Z for IK calculation
                        rv = ik_solver.inverse_kinematics_separated(
                            current_ee_x, current_ee_y, target_ee_z, right_handed=current_right_handed
                        )
                        

                        if rv is None:
                            logger.warning(f" IK calculation failed, using legacy method")
                        else:
                            # Extract robot Z from IK result (apply minimum limit)
                            robot_z = max(float(rv[2]), -240)
                            

                            logger.info(f" [DEBUG] move_z_position: considering end effector offset")
                            logger.info(f" - end effector: {end_effector}, with_tip: {tip}")
                            logger.info(f" - effective end effector for offset: {effective_end_effector_for_offset}, effective with_tip: {effective_with_tip}, tool_name: {effective_tool_name}")
                            logger.info(f" - end effector offset: {ee_offset}")
                            logger.info(f" - Current robot Z: {current_robot_z:.2f}mm")
                            logger.info(f" - Current end effector tip Z: {current_ee_z:.2f}mm")
                            logger.info(f" - Target end effector tip Z: {target_ee_z:.2f}mm")
                            logger.info(f" - Calculated robot Z: {robot_z:.2f}mm")
                            logger.info(f" - Maintaining current angles: angle1={current_angle1:.2f}°, angle2={current_angle2:.2f}°")
                            

                            # Move using move_to_angle: keep current angles, change only Z
                            result = self.interface_manager.scara.move_to_angle(
                                current_angle1,
                                current_angle2,
                                robot_z,  # Robot Z coordinate considering end effector offset
                                0, # r = 0
                                speed=speed,
                                roughly=0,
                                skip_gripper_rotation=True  # Skip gripper rotation when using pipette
                            )
                            return result
                    else:
                        logger.warning(f" Cannot get current position, using legacy method")
                except Exception as e:
                    logger.warning(f" Error in move_z_position processing: {e}, using legacy method")
                    import traceback
                    traceback.print_exc()
            

            # Check calculate_from_surface flag (dynamic Z coordinate calculation)
            calculate_from_surface = parameters.get('calculate_from_surface', False)
            if calculate_from_surface:
                # Dynamically calculate Z coordinate using tube status
                source_id = parameters.get('source_id')
                tool_center_z = parameters.get('tool_center_z')
                tool_size_z = parameters.get('tool_size_z')
                surface_offset = parameters.get('surface_offset', 5.0)
                

                if source_id and self.tube_interface:
                    try:
                        # Get current liquid surface height (after aspiration)
                        current_height_mm = self.tube_interface.get_liquid_height(source_id)
                        if current_height_mm is not None and tool_center_z is not None and tool_size_z is not None:
                            # Z coordinate calculation:
                            # tool_center_z is tube top; subtract tool_size_z for bottom
                            # Add liquid height and offset to get pipette tip target Z
                            

                            # Calculate tube bottom Z (robot coordinate system)
                            tube_bottom_z = tool_center_z - tool_size_z
                            

                            # Calculate pipette tip target Z (robot coordinate system)
                            # tube_bottom + liquid_height + offset = target pipette tip Z
                            target_pipette_tip_z = tube_bottom_z + current_height_mm + surface_offset
                            

                            logger.info(f" [DEBUG] Dynamic z-coordinate calculation:")
                            logger.info(f" - source_id: {source_id}")
                            logger.info(f" - tool_center_z: {tool_center_z:.2f} mm (tube top, robot coordinate system)")
                            logger.info(f" - tool_size_z: {tool_size_z:.2f} mm")
                            logger.info(f" - tube bottom z: {tube_bottom_z:.2f} mm (robot coordinate system)")
                            logger.info(f" - Current liquid surface height: {current_height_mm:.2f} mm")
                            logger.info(f" - surface_offset: {surface_offset:.2f} mm")
                            logger.info(f" - Target pipette tip z: {target_pipette_tip_z:.2f} mm (robot coordinate system)")
                            logger.info(f" - Note: move_end_effector receives pipette tip position")
                            

                            # Update Z coordinate (move_end_effector receives pipette tip position)
                            xyz[2] = target_pipette_tip_z
                        else:
                            logger.warning(f" Dynamic calculation failed: source_id={source_id}, current_height={current_height_mm}, tool_center_z={tool_center_z}, tool_size_z={tool_size_z}")
                    except Exception as e:
                        logger.error(f" Dynamic z coordinate calculation error: {e}")
                        import traceback
                        traceback.print_exc()
                else:
                    logger.warning(f" Dynamic calculation not possible: source_id={source_id}, tube_interface={self.tube_interface is not None}")
            

            # Debug: check speed parameter
            logger.info(f" [DEBUG] _execute_scara_move_end_effector: speed parameter={parameters.get('speed', 100)} (type: {type(parameters.get('speed', 100))}), converted speed={speed}")
            

            # Check and apply calibration data
            calibration_angles = parameters.get('calibration_angles')  # {'angle1': float, 'angle2': float} or None
            tool_name = parameters.get('tool_name')  # 'tip1', 'tip2', 'tip3', 'mea-measure', 'mea2', etc.
            

            # Store tool_name for use by subsequent commands (e.g. move_z_position)
            if tool_name:
                self.last_tool_name = tool_name
            grid_row = parameters.get('grid_row')  # Grid row (0-indexed)
            grid_col = parameters.get('grid_col')  # Grid column (0-indexed)
            

            # Debug: check calibration parameters
            logger.info(f" [DEBUG] Checking calibration parameters:")
            logger.info(f" - calibration_angles: {calibration_angles}")
            logger.info(f" - tool_name: {tool_name}")
            logger.info(f" - grid_row: {grid_row}")
            logger.info(f" - grid_col: {grid_col}")
            

            # When grid_row and grid_col are present: ignore xyz from cmd list, use only grid info.
            # This ensures consistent coordinate calculation for both sequential and jump-to-grid moves.
            use_grid_info_only = (grid_row is not None and grid_col is not None and calibration_angles and tool_name)
            

            # Convert xyz array to dict (used only when grid_row/grid_col are absent)
            # When grid_row/grid_col are present, the value will be recalculated from grid info later
            target_position = {'x': xyz[0], 'y': xyz[1], 'z': xyz[2]}
            

            if use_grid_info_only:
                logger.info(f" [Grid-based calculation] grid_row={grid_row}, grid_col={grid_col} present, ignoring cmd list xyz and using grid only.")
                logger.info(f" - cmd list xyz (ignored): x={xyz[0]:.2f}, y={xyz[1]:.2f}, z={xyz[2]:.2f}")
            

            # Use calibrated angles if available
            if calibration_angles and tool_name:
                logger.info(f" [DEBUG] Entering calibration logic: calibration_angles={calibration_angles is not None}, tool_name={tool_name}")
                angle1_0 = calibration_angles.get('angle1')
                angle2_0 = calibration_angles.get('angle2')
                calib_end_effector = calibration_angles.get('end_effector', end_effector)
                calib_with_tip = calibration_angles.get('with_tip', tip)
                

                # For mea2/mea-measure apply action: set servo before calibration logic
                # Take action: no servo setup needed (uses Pipette with tip)
                # Apply action: servo at 75 degrees needed (uses Angled Pipette)
                is_take = self._is_take_action(parameters)
                if not is_take:  # Set servo only for apply action
                    effective_ee_for_check = calib_end_effector if calib_end_effector == 'Angled Pipette' else end_effector
                    if self._is_angled_pipette_mode(effective_ee_for_check, tool_name):
                        if self.interface_manager.connected_interfaces['servo']:
                            try:
                                logger.info(f" [Angled Pipette - mea2/mea-measure access (apply)] Setting Servo to 75° (speed 10) first...")
                                result_servo = self.interface_manager.servo.move_to_angle(75.0, wait_time=2.0, speed=10)
                                if result_servo:
                                    logger.info(f" Servo 75° (speed 10) set completed")
                                else:
                                    logger.warning(f" Servo 75 degree setting failed")
                            except Exception as e:
                                logger.warning(f" Servo setting error: {e}")
                        else:
                            logger.warning(f" Servo interface is not connected")
                else:
                    logger.info(f" [Take action] Servo setup skipped (Pipette with tip)")
                

                # Angled Pipette is internally treated as pipette; calib_end_effector is kept as-is
                # calib_end_effector is preserved; end_effector is used as reference when needed
                

                logger.info(f" [DEBUG] Calibration angle values: angle1_0={angle1_0}, angle2_0={angle2_0}")
                logger.info(f" [DEBUG] Grid position: grid_row={grid_row}, grid_col={grid_col}")
                

                if angle1_0 is not None and angle2_0 is not None:
                    # Set grid_row and grid_col to 0 if None
                    if grid_row is None:
                        grid_row = 0
                    if grid_col is None:
                        grid_col = 0
                    

                    # For row=0, col=0: apply end_effector offset correction (same as test logic)
                    if grid_row == 0 and grid_col == 0:
                        # Apply end_effector offset correction
                        corrected_angle1 = angle1_0
                        corrected_angle2 = angle2_0
                        

                        try:
                            from ikine2 import inv_kinematics
                            

                            # Get the actual position saved during calibration
                            from utils.calibration_manager import CalibrationManager
                            calib_manager = CalibrationManager()
                            

                            # Check action parameter (take or apply)
                            action = 'take' if self._is_take_action(parameters) else 'apply'
                            calib_position = calib_manager.get_calibrated_position(tool_name, action=action)
                            

                            if calib_position:
                                # Actual taught position saved during calibration (end effector tip)
                                x_0_0_actual = calib_position[0]
                                y_0_0_actual = calib_position[1]
                                

                                # Apply position correction for gripper on MEA tools (X and Y)
                                # calib_end_effector may be Angled Pipette, so also check end_effector
                                effective_end_effector_for_gripper = calib_end_effector if calib_end_effector != 'Angled Pipette' else end_effector
                                if effective_end_effector_for_gripper == 'gripper' and 'mea' in tool_name.lower():
                                    try:
                                        position_offset = calib_manager.get_gripper_position_calibration(tool_name)
                                        if position_offset is not None:
                                            x_offset, y_offset = position_offset
                                            x_0_0_actual = x_0_0_actual + x_offset
                                            y_0_0_actual = y_0_0_actual + y_offset
                                            logger.info(f" [Position correction] {tool_name}: Applied X correction value {x_offset:.2f}mm, Y correction value {y_offset:.2f}mm -> x_0_0_actual={x_0_0_actual:.2f}mm, y_0_0_actual={y_0_0_actual:.2f}mm")
                                    except Exception as e:
                                        logger.warning(f" [Position correction] {tool_name}: Position correction value load failed: {e}")
                                

                                # Get end effector offset used during calibration
                                calib_offset = calib_manager.get_calibration_end_effector_offset(tool_name, action=action)
                                

                                # Get current end effector offset (pass tool_name for mea2/mea-measure)
                                # Take action: use pipette with_tip=True
                                # Apply action: use Angled Pipette with_tip=False
                                is_take = self._is_take_action(parameters)
                                if is_take and self._is_angled_pipette_mode(end_effector, tool_name):
                                    # Take action: Pipette with tip
                                    effective_end_effector_for_offset = 'pipette'
                                    effective_with_tip = True
                                elif not is_take and self._is_angled_pipette_mode(end_effector, tool_name):
                                    # Apply action: Angled Pipette
                                    effective_end_effector_for_offset = 'Angled Pipette'
                                    effective_with_tip = False
                                else:
                                    # General case
                                    effective_end_effector_for_offset = end_effector if end_effector == 'Angled Pipette' else calib_end_effector
                                    effective_with_tip = calib_with_tip
                                

                                ee_offset_current = self.interface_manager.scara.get_end_effector_offset(effective_end_effector_for_offset, effective_with_tip, tool_name)
                                

                                # Log offset info
                                if calib_offset:
                                    offset_diff_x = ee_offset_current['x'] - calib_offset['x']
                                    offset_diff_y = ee_offset_current['y'] - calib_offset['y']
                                    logger.info(f" [Calibration] {tool_name} offset info:")
                                    logger.info(f" - Calibration offset: x={calib_offset['x']:.2f}, y={calib_offset['y']:.2f}, z={calib_offset['z']:.2f}")
                                    logger.info(f" - Current offset: x={ee_offset_current['x']:.2f}, y={ee_offset_current['y']:.2f}, z={ee_offset_current['z']:.2f}")
                                    logger.info(f" - Offset diff: x={offset_diff_x:.2f}, y={offset_diff_y:.2f}")
                                

                                # Key: calibration position is the end effector tip position calculated with calibration offset
                                # Although independent of offset, IK result varies with offset used
                                # Therefore: restore original angles using calibration offset IK for best accuracy
                                

                                # Run IK with calibration offset to restore original angles
                                if calib_offset:
                                    ik_solver_calib = inv_kinematics(dx=calib_offset['x'], dy=calib_offset['y'], dz=calib_offset['z'])
                                    

                                    # Determine coordinate mode (also handles Angled Pipette)
                                    effective_end_effector = 'pipette' if end_effector == 'Angled Pipette' else calib_end_effector
                                    right_handed = self._determine_right_handed(effective_end_effector, tool_name)
                                    if right_handed is None:
                                        # mea-measure, mea2 are left-handed; others are right-handed
                                        if tool_name and tool_name.lower() in ['mea-measure', 'mea2']:
                                            right_handed = False
                                        else:
                                            right_handed = True
                                    logger.info(f" [Calibration] Tool coordinate mode: {'right-handed' if right_handed else 'left-handed'} (tool: {tool_name})")
                                    

                                    # Run IK with calibration offset to restore original angles
                                    restored_angles = ik_solver_calib.inverse_kinematics_separated(
                                        x_0_0_actual, y_0_0_actual, 0, right_handed=right_handed
                                    )
                                    

                                    if restored_angles:
                                        restored_angle1, restored_angle2, _ = restored_angles
                                        

                                        # Verify with forward kinematics
                                        pos_verify = ik_solver_calib.forward_kinematics(restored_angle1, restored_angle2, 0)
                                        x_verify, y_verify, _ = pos_verify
                                        error = math.sqrt((x_verify - x_0_0_actual)**2 + (y_verify - y_0_0_actual)**2)
                                        

                                        logger.info(f" [Calibration] Moving {tool_name} to calibration position:")
                                        logger.info(f" - Calibration angles: angle1={angle1_0:.2f}°, angle2={angle2_0:.2f}°")
                                        logger.info(f" - Actual taught position (end effector tip): x={x_0_0_actual:.2f}, y={y_0_0_actual:.2f}")
                                        logger.info(f" - Restored angles: angle1={restored_angle1:.2f}°, angle2={restored_angle2:.2f}°")
                                        logger.info(f" - Verify position: x={x_verify:.2f}, y={y_verify:.2f}, error={error:.3f}mm")
                                        

                                        # Use restored angles if error is small; keep original if large
                                        if error <= 1.0:
                                            corrected_angle1 = restored_angle1
                                            corrected_angle2 = restored_angle2
                                        else:
                                            logger.warning(f" [Calibration] Error too large ({error:.3f}mm > 1mm), using original angle")
                                            corrected_angle1 = angle1_0
                                            corrected_angle2 = angle2_0
                                    else:
                                        logger.warning(f" [Calibration] {tool_name} IK calculation failed, using original angle")
                                        corrected_angle1 = angle1_0
                                        corrected_angle2 = angle2_0
                                else:
                                    # Use original angles if no calibration offset info
                                    logger.warning(f" [Calibration] {tool_name} no offset info during calibration. Using original angle")
                                    corrected_angle1 = angle1_0
                                    corrected_angle2 = angle2_0
                            else:
                                logger.warning(f" [Calibration] Cannot find saved actual position for {tool_name} calibration.")
                                corrected_angle1 = angle1_0
                                corrected_angle2 = angle2_0
                        except Exception as e:
                            logger.warning(f" [Calibration] Error calculating end_effector offset correction for {tool_name}: {e}, using original angle")
                            corrected_angle1 = angle1_0
                            corrected_angle2 = angle2_0
                        

                        final_angle1 = corrected_angle1
                        final_angle2 = corrected_angle2
                    else:
                        # For row!=0 or col!=0: calculate final angles with grid offset
                        # Convert Angled Pipette to pipette (correct offset used via tool_name internally)
                        effective_end_effector_for_grid = 'pipette' if calib_end_effector == 'Angled Pipette' else calib_end_effector
                        

                        # Check action parameter (take or apply)
                        action = 'take' if self._is_take_action(parameters) else 'apply'
                        

                        final_angles = self._calculate_grid_angles_from_calibration(
                            tool_name, angle1_0, angle2_0, grid_row, grid_col,
                            effective_end_effector_for_grid, calib_with_tip, action=action
                        )
                        

                        if final_angles:
                            final_angle1, final_angle2 = final_angles
                            logger.info(f" [Calibration applied] Using calibrated angles for {tool_name}")
                            logger.info(f" - Calibrated [0,0] angles: angle1={angle1_0:.2f}°, angle2={angle2_0:.2f}°")
                            logger.info(f" - Grid position: row={grid_row}, col={grid_col}")
                            logger.info(f" - Final angles: angle1={final_angle1:.2f}°, angle2={final_angle2:.2f}°")
                            logger.info(f" - End Effector: {calib_end_effector}, With Tip: {calib_with_tip}")
                        else:
                            logger.warning(f" [Calibration] {tool_name} grid angle calculation failed, using legacy method")
                            final_angle1 = None
                            final_angle2 = None
                    

                    # Move using calculated angles if available
                    if final_angle1 is not None and final_angle2 is not None:
                        # For move_xy_position: keep Z at current position (X, Y move only)
                        # Move to grid-based angles; keep current Z
                        # Get current Z coordinate
                        current_pos = self.interface_manager.scara.get_current_position()
                        if current_pos:
                            current_z = current_pos['z']
                            logger.info(f" [Grid-based calculation] move_xy_position: Keeping current Z ({current_z:.2f}mm)")
                        else:
                            # Use Z=0 if current position cannot be retrieved
                            current_z = 0
                            logger.warning(f" [Grid-based calculation] Cannot get current position, using Z=0")
                        

                        # Debug: verify position before grid move (for comparison with target)
                        from ikine2 import inv_kinematics
                        from utils.calibration_manager import CalibrationManager
                        calib_manager = CalibrationManager()
                        action = 'take' if self._is_take_action(parameters) else 'apply'
                        calib_offset = calib_manager.get_calibration_end_effector_offset(tool_name, action=action)
                        if calib_offset:
                            ik_solver_debug = inv_kinematics(dx=calib_offset['x'], dy=calib_offset['y'], dz=calib_offset['z'])
                        else:
                            effective_end_effector_for_offset = 'Angled Pipette' if action == 'apply' and self._is_angled_pipette_mode(end_effector, tool_name) else 'pipette'
                            effective_with_tip = False if action == 'apply' and self._is_angled_pipette_mode(end_effector, tool_name) else True
                            ee_offset_debug = self.interface_manager.scara.get_end_effector_offset(effective_end_effector_for_offset, effective_with_tip, tool_name)
                            ik_solver_debug = inv_kinematics(dx=ee_offset_debug['x'], dy=ee_offset_debug['y'], dz=ee_offset_debug['z'])
                        

                        # Pre-move position (via forward kinematics)
                        if current_pos:
                            pre_move_angle1 = current_pos.get('angle1', 0)
                            pre_move_angle2 = current_pos.get('angle2', 0)
                            pre_move_pos = ik_solver_debug.forward_kinematics(pre_move_angle1, pre_move_angle2, current_z)
                            pre_move_x, pre_move_y, _ = pre_move_pos
                            logger.info(f" [Grid movement DEBUG] Position before move (end effector tip): x={pre_move_x:.3f}, y={pre_move_y:.3f} (angle1={pre_move_angle1:.2f}°, angle2={pre_move_angle2:.2f}°)")
                        

                        # Target position calculation (for grid move)
                        if grid_row is not None and grid_col is not None:
                            # Calculate grid move target position
                            calib_position = calib_manager.get_calibrated_position(tool_name, action=action)
                            if calib_position:
                                x_0_0_robot = calib_position[0]
                                y_0_0_robot = calib_position[1]
                                

                                # Calculate grid offset
                                import json
                                from pathlib import Path
                                table_coords_file = Path("table_coordinates.json")
                                if table_coords_file.exists():
                                    with open(table_coords_file, 'r', encoding='utf-8') as f:
                                        table_coords = json.load(f)
                                    tool_data = table_coords.get('tools', {}).get(tool_name)
                                    if tool_data:
                                        grid_pattern = tool_data.get('grid_pattern', {})
                                        grid_center_coords = grid_pattern.get('grid_center_coordinates', [])
                                        if grid_center_coords:
                                            grid_cols = 2 if 'mea' in tool_name else 12
                                            grid_index = grid_row * grid_cols + grid_col
                                            if grid_index < len(grid_center_coords):
                                                grid_0_0_center = grid_center_coords[0]
                                                target_grid_center = grid_center_coords[grid_index]
                                                grid_offset_x = target_grid_center['x'] - grid_0_0_center['x']
                                                grid_offset_y = target_grid_center['y'] - grid_0_0_center['y']
                                                target_x_robot = x_0_0_robot + grid_offset_x
                                                target_y_robot = y_0_0_robot + grid_offset_y
                                                logger.info(f" [Grid movement DEBUG] Target position (end effector tip): x={target_x_robot:.3f}, y={target_y_robot:.3f} (grid_row={grid_row}, grid_col={grid_col})")
                        

                        # For pipette end effector (including Angled Pipette): skip gripper rotation
                        skip_gripper_rotation = (end_effector in ['pipette', 'Angled Pipette'])
                        # Move directly to calculated angles
                        # When grid_row/grid_col are present: ignore xyz, use grid-based angles only
                        # Keep current Z (move_xy_position moves X, Y only)
                        logger.info(f" [Grid movement DEBUG] Move command: angle1={final_angle1:.3f}°, angle2={final_angle2:.3f}°, z={current_z:.2f}mm")
                        result = self.interface_manager.scara.move_to_angle(
                            final_angle1,
                            final_angle2,
                            current_z,  # Keep current Z (move_xy_position moves X, Y only)
                            0, # r = 0
                            speed=speed,
                            roughly=0,
                            skip_gripper_rotation=skip_gripper_rotation
                        )
                        

                        # Debug: verify actual position after grid move
                        if result:
                            post_move_pos = self.interface_manager.scara.get_current_position()
                            if post_move_pos:
                                post_move_angle1 = post_move_pos.get('angle1', 0)
                                post_move_angle2 = post_move_pos.get('angle2', 0)
                                post_move_z = post_move_pos.get('z', current_z)
                                post_move_pos_fk = ik_solver_debug.forward_kinematics(post_move_angle1, post_move_angle2, post_move_z)
                                post_move_x, post_move_y, _ = post_move_pos_fk
                                logger.info(f" [Grid movement DEBUG] Actual position after move (end effector tip): x={post_move_x:.3f}, y={post_move_y:.3f} (angle1={post_move_angle1:.2f}°, angle2={post_move_angle2:.2f}°)")
                                

                                # Compare target vs actual position
                                if grid_row is not None and grid_col is not None and calib_position:
                                    error_x = target_x_robot - post_move_x
                                    error_y = target_y_robot - post_move_y
                                    error_distance = math.sqrt(error_x**2 + error_y**2)
                                    logger.info(f" [Grid movement DEBUG] Position error analysis:")
                                    logger.info(f" - Target position: x={target_x_robot:.3f}, y={target_y_robot:.3f}")
                                    logger.info(f" - Actual position: x={post_move_x:.3f}, y={post_move_y:.3f}")
                                    logger.info(f" - Error: Δx={error_x:.3f}mm, Δy={error_y:.3f}mm, distance={error_distance:.3f}mm")
                                    if error_distance > 0.5:
                                        logger.warning(f" [Grid movement DEBUG] Large position error! (distance={error_distance:.3f}mm > 0.5mm)")
                                

                                # Compare with previous position (check cumulative error in sequential grid moves)
                                if current_pos:
                                    movement_x = post_move_x - pre_move_x
                                    movement_y = post_move_y - pre_move_y
                                    movement_distance = math.sqrt(movement_x**2 + movement_y**2)
                                    logger.info(f" [Grid movement DEBUG] Move distance: Δx={movement_x:.3f}mm, Δy={movement_y:.3f}mm, distance={movement_distance:.3f}mm")
                        

                        # For Angled Pipette (mea2/mea-measure): offset move is done after move_z_position
                        # Order: servo 75 -> move x,y -> move z -> move offset x,y -> spit -> return x,y -> move to top
                        return result
                    else:
                        logger.warning(f" [Calibration] {tool_name} grid angle calculation failed, using legacy method")
            else:
                # No calibration parameters
                logger.info(f" [DEBUG] No calibration parameters - using default method")
                logger.info(f" - calibration_angles: {calibration_angles}")
                logger.info(f" - tool_name: {tool_name}")
            

            # Fall back to legacy method if no calibration data or calculation failed
            # When grid_row/grid_col are present but no calibration: cannot use grid, use legacy method
            # Note: grid info cannot be used without calibration
            if use_grid_info_only:
                logger.warning(f" [Grid-based calculation] grid_row={grid_row}, grid_col={grid_col} present but no calibration, using legacy method")
            

            # For move_xy_position (even without grid): keep current Z
            action = parameters.get('action')
            if action == 'move_xy_position':
                current_pos = self.interface_manager.scara.get_current_position()
                if current_pos:
                    current_z = current_pos['z']
                    target_position['z'] = current_z  # Overwrite with current Z
                    logger.info(f" [move_xy_position] Keeping current Z: {current_z:.2f}mm (xyz[2]={xyz[2]:.2f}mm ignored)")
                else:
                    logger.warning(f" [move_xy_position] Cannot get current position, using Z=0")
            

            logger.info(f" SCARA movement: {end_effector} -> {target_position} (tip: {tip})")
            logger.info(f"Speed: {speed}, Roughness: 0")
            

            # Set servo angle for mea2/mea-measure access
            # Take action: servo at 60 degrees (Pipette with tip)
            # Apply action: servo at 75 degrees (Angled Pipette)
            is_take = self._is_take_action(parameters)
            if not is_take and self._is_angled_pipette_mode(end_effector, tool_name):
                if self.interface_manager.connected_interfaces['servo']:
                    try:
                        logger.info(f" [Angled Pipette - mea2/mea-measure access (apply)] Setting Servo to 75° (speed 10) first...")
                        result_servo = self.interface_manager.servo.move_to_angle(75.0, wait_time=2.0, speed=10)
                        if result_servo:
                            logger.info(f" Servo 75° (speed 10) set completed")
                        else:
                            logger.warning(f" Servo 75 degree setting failed")
                    except Exception as e:
                        logger.warning(f" Servo setting error: {e}")
                else:
                    logger.warning(f" Servo interface is not connected")
            elif is_take and self._is_angled_pipette_mode(end_effector, tool_name):
                if self.interface_manager.connected_interfaces['servo']:
                    try:
                        logger.info(f" [Pipette - mea2/mea-measure access (take)] Setting Servo to 60° first...")
                        result_servo = self.interface_manager.servo.move_to_angle(60.0, wait_time=2.0)
                        if result_servo:
                            logger.info(f" Servo 60° set completed")
                        else:
                            logger.warning(f" Servo 60 degree setting failed")
                    except Exception as e:
                        logger.warning(f" Servo setting error: {e}")
                else:
                    logger.warning(f" Servo interface is not connected")
            

            # Determine effective end effector for SCARA
            # Take action: use pipette
            # Apply action: Angled Pipette is treated as pipette internally
            is_take = self._is_take_action(parameters)
            if is_take and self._is_angled_pipette_mode(end_effector, tool_name):
                # Take action: Pipette with tip
                effective_end_effector_for_scara = 'pipette'
                effective_with_tip = True
            elif not is_take and self._is_angled_pipette_mode(end_effector, tool_name):
                # Apply action: Angled Pipette treated as pipette internally
                effective_end_effector_for_scara = 'pipette'
                effective_with_tip = False
            else:
                # General case
                effective_end_effector_for_scara = 'pipette' if end_effector in ['pipette', 'Angled Pipette'] else end_effector
                effective_with_tip = tip
            

            # Note: move_end_effector updates state automatically; direct update not needed
            # (existing code still works - redundant but harmless)
            # if effective_end_effector_for_scara != self.interface_manager.scara.current_end_effector:
            #     logger.info(f'[move_end_effector] end_effector update: {self.interface_manager.scara.current_end_effector} -> {effective_end_effector_for_scara}')
            # self.interface_manager.scara.current_end_effector = effective_end_effector_for_scara
            

            # Determine coordinate calculation mode by tool (only when no calibration info)
            # Angled Pipette is treated as pipette
            effective_end_effector_for_handed = 'pipette' if end_effector in ['pipette', 'Angled Pipette'] else end_effector
            right_handed = self._determine_right_handed(effective_end_effector_for_handed, tool_name)
            if right_handed is not None:
                logger.info(f" Tool-specific coordinate calculation method: {'right-handed' if right_handed else 'left-handed'} (tool: {tool_name})")
            

            # Apply gripper position correction when accessing MEA tools
            if end_effector == 'gripper' and tool_name and 'mea' in tool_name.lower():
                try:
                    from utils.calibration_manager import CalibrationManager
                    calib_manager = CalibrationManager()
                    position_offset = calib_manager.get_gripper_position_calibration(tool_name)
                    if position_offset is not None:
                        x_offset, y_offset = position_offset
                        # Apply correction to target_position
                        target_position['x'] = target_position['x'] + x_offset
                        target_position['y'] = target_position['y'] + y_offset
                        logger.info(f" [Position correction] {tool_name}: Applied X correction value {x_offset:.2f}mm, Y correction value {y_offset:.2f}mm -> target_position=({target_position['x']:.2f}, {target_position['y']:.2f})")
                except Exception as e:
                    logger.warning(f" [Position correction] {tool_name}: Position correction value load failed: {e}")
            

            # Execute SCARA move command
            # Take action: pipette with_tip=True
            # Apply action: pipette with_tip=False (Angled Pipette is treated as pipette internally)
            result = self.interface_manager.scara.move_end_effector(
                ee_type=effective_end_effector_for_scara,
                target_position=target_position,
                with_tip=effective_with_tip,
                speed=speed,
                roughly=0,
                right_handed=right_handed,
                tool_name=tool_name
            )
            

            # For Angled Pipette (mea2/mea-measure): offset move is done before spit
            # Order: servo 75 -> move x,y -> move z -> move offset x,y -> spit -> return x,y -> move to top
            

            # Save MEA pick/place context if applicable (for quantity management)
            if result and end_effector == 'gripper':
                # Check action and tool_name parameters
                action = parameters.get('action')
                target_name = parameters.get('tool_name') or tool_name
                

                if action in ['pick', 'place'] and target_name and 'mea' in target_name.lower():
                    location = target_name.lower()
                    # For pick action: save context (quantity decreases on gripper close)
                    if action == 'pick':
                        self.current_pick_context = {
                            'action': 'pick',
                            'location': location,
                            'tool_name': target_name
                        }
                        logger.info(f" [MEA Stack] Saving Pick context: {location} (quantity will decrease on gripper close)")
                    # For place action: save context (quantity increases on gripper open)
                    elif action == 'place':
                        self.current_place_context = {
                            'action': 'place',
                            'location': location,
                            'tool_name': target_name
                        }
                        logger.info(f" [MEA Stack] Saving Place context: {location} (quantity will increase on gripper open)")
            

            return result
            

        except Exception as e:
            logger.error(f" SCARA movement error: {e}")
            import traceback
            traceback.print_exc()
            return False
    

    def _is_take_action(self, parameters: Dict[str, Any]) -> bool:
        """
        Check if the action is take or mix.
        

        Args:
            parameters: Command parameters
        

        Returns:
            bool: True if action is 'take' or 'mix'
        """
        action = parameters.get('action')
        command_type = parameters.get('type')
        # True if action is 'take'/'mix' or type is 'take'/'mix'
        return action in ['take', 'mix'] or command_type in ['take', 'mix']
    

    def _is_angled_pipette_mode(self, end_effector: str, tool_name: Optional[str] = None,
                                current_end_effector: Optional[str] = None) -> bool:
        """
        Check if Angled Pipette mode is active.
        

        Condition: when end_effector is 'pipette' or 'Angled Pipette' and
              tool_name is 'mea2' or 'mea-measure'.
        

        Args:
            end_effector: End effector type ('pipette' or 'Angled Pipette')
            tool_name: Tool name (e.g. 'mea2', 'mea-measure')
            current_end_effector: Currently set end effector (optional, uses end_effector if absent)
        

        Returns:
            bool: True if Angled Pipette mode is active
        """
        # Use end_effector if current_end_effector is not provided
        if current_end_effector is None:
            current_end_effector = end_effector
        

        # Condition: end_effector is 'pipette' or 'Angled Pipette', and tool_name is mea2 or mea-measure
        is_pipette = (end_effector == 'pipette' or end_effector == 'Angled Pipette' or
                      current_end_effector == 'pipette' or current_end_effector == 'Angled Pipette')
        

        if not is_pipette:
            return False
        

        if not tool_name:
            return False
        

        tool_name_lower = tool_name.lower()
        return tool_name_lower in ['mea2', 'mea-measure']
    

    def _determine_right_handed(self, end_effector: str, tool_name: Optional[str] = None) -> Optional[bool]:
        """
        Determine coordinate calculation mode (right-handed / left-handed) per tool.
        

        Rules:
        - Pipette or Angled Pipette:
          - tip box (tip1, tip2, tip3), tip-trash: right-handed
          - mea2, mea-measure, all sources, liq-trash: left-handed
        - Gripper: always left-handed
        

        Args:
            end_effector: End effector type ('gripper', 'pipette', or 'Angled Pipette')
            tool_name: Tool name (e.g. 'tip1', 'tip2', 'tip3', 'mea-measure', 'mea2', 'SOURCE1')
        

        Returns:
            Optional[bool]: True (right-handed), False (left-handed), None (auto-select)
        """
        # Treat 'Angled Pipette' as 'pipette'
        if end_effector == 'Angled Pipette':
            end_effector = 'pipette'
        

        if end_effector == 'gripper':
            # Gripper is always left-handed
            return False
        

        elif end_effector == 'pipette':
            if not tool_name:
                # Auto-select if no tool_name
                return None
            

            tool_name_lower = tool_name.lower()
            

            # Right-handed tools
            right_handed_tools = [
                'tip1', 'tip2', 'tip3', # tip box
                'tip-trash' # tip-trash
            ]
            

            # Left-handed tools
            left_handed_tools = [
                'mea2', # mea2
                'mea-measure', # mea-measure
                'liq-trash', # liq-trash
            ]
            

            # Check if tool is in right-handed list
            if any(tool in tool_name_lower for tool in right_handed_tools):
                return True
            

            # Check if tool is in left-handed list
            if any(tool in tool_name_lower for tool in left_handed_tools):
                return False
            

            # source* tools are left-handed
            if tool_name_lower.startswith('source'):
                return False
            

            # Auto-select if tool_name is not explicitly specified
            return None
        

        # Unknown end_effector type
        return None
    

    def _calculate_grid_angles_from_calibration(self, tool_name: str, angle1_0: float, angle2_0: float,
                                                 row: int, col: int, end_effector: str, with_tip: bool,
                                                 action: str = None) -> Optional[Tuple[float, float]]:
        """
        Calculate joint angles for grid position [row, col] from calibrated [0,0] angles.
        

        Args:
            tool_name: Tool name ('tip1', 'tip2', 'tip3', 'mea-measure', 'mea2')
            angle1_0: Calibrated [0,0] angle1
            angle2_0: Calibrated [0,0] angle2
            row: Grid row (0-indexed)
            col: Grid column (0-indexed)
            end_effector: End effector type
            with_tip: Whether tip is attached
        

        Returns:
            Optional[Tuple[float, float]]: (final_angle1, final_angle2) or None
        """
        try:
            from ikine2 import inv_kinematics
            import yaml
            from pathlib import Path
            

            # Load grid info from table_coordinates.json
            table_coords_file = Path("table_coordinates.json")
            if not table_coords_file.exists():
                logger.warning(f" table_coordinates.json not found.")
                return None
            

            with open(table_coords_file, 'r', encoding='utf-8') as f:
                table_coords = json.load(f)
            

            tool_data = table_coords.get('tools', {}).get(tool_name)
            if not tool_data:
                logger.warning(f" {tool_name} data not found in table_coordinates.json.")
                return None
            

            grid_pattern = tool_data.get('grid_pattern', {})
            distance = grid_pattern.get('distance', {})
            distance_x = distance.get('x', 0)
            distance_y = distance.get('y', 0)
            

            # Get end effector offset
            scara = self.interface_manager.scara
            if not scara:
                logger.warning(" ScaraInterface not found.")
                return None
            

            # Get end effector offset based on action (take or apply)
            # Take action: use pipette with_tip=True
            # Apply action: use Angled Pipette with_tip=False
            if action is None:
                # Default: if Angled Pipette -> apply; if pipette with tip -> take
                if end_effector == 'Angled Pipette':
                    action = 'apply'
                elif end_effector == 'pipette' and with_tip:
                    action = 'take'
                else:
                    action = 'apply'  # Default
            

            if action == 'take' and self._is_angled_pipette_mode(end_effector, tool_name):
                # Take action: Pipette with tip
                effective_end_effector_for_offset = 'pipette'
                effective_with_tip = True
                logger.info(f" [Grid calculation] {tool_name} (take): Using 'pipette' with tip for end effector offset")
            elif action == 'apply' and self._is_angled_pipette_mode(end_effector, tool_name):
                # Apply action: Angled Pipette
                effective_end_effector_for_offset = 'Angled Pipette'
                effective_with_tip = False
                logger.info(f" [Grid calculation] {tool_name} (apply): Using 'Angled Pipette' for end effector offset")
            else:
                # General case
                effective_end_effector_for_offset = end_effector
                effective_with_tip = with_tip
            

            ee_offset = scara.get_end_effector_offset(effective_end_effector_for_offset, effective_with_tip, tool_name)
            logger.info(f" [Grid calculation] {tool_name}: End effector offset: {ee_offset} (effective_end_effector={effective_end_effector_for_offset}, with_tip={effective_with_tip}, action={action})")
            

            # Get actual calibrated position to correct for end effector offset differences
            from utils.calibration_manager import CalibrationManager
            calib_manager = CalibrationManager()
            

            # Check action parameter (take or apply)
            if action is None:
                # Default: if Angled Pipette -> apply; if pipette with tip -> take
                if end_effector == 'Angled Pipette':
                    action = 'apply'
                elif end_effector == 'pipette' and with_tip:
                    action = 'take'
                else:
                    action = 'apply'  # Default
            

            calib_position = calib_manager.get_calibrated_position(tool_name, action=action)
            

            # Get end effector offset used during calibration
            calib_offset = calib_manager.get_calibration_end_effector_offset(tool_name, action=action)
            

            # Forward kinematics from calibrated [0,0] angles
            # Use calibration offset if available; otherwise use current offset
            if calib_offset:
                # Use calibration offset for better accuracy
                ik_solver_calib = inv_kinematics(dx=calib_offset['x'], dy=calib_offset['y'], dz=calib_offset['z'])
                pos_0_0_calc = ik_solver_calib.forward_kinematics(angle1_0, angle2_0, 0)
                x_0_0_calc, y_0_0_calc, z_0_0_calc = pos_0_0_calc
                logger.info(f" [Grid calculation] {tool_name}: Using calibration offset for forward kinematics")
            else:
                # Use current offset if no calibration offset
                ik_solver = inv_kinematics(dx=ee_offset['x'], dy=ee_offset['y'], dz=ee_offset['z'])
                pos_0_0_calc = ik_solver.forward_kinematics(angle1_0, angle2_0, 0)
                x_0_0_calc, y_0_0_calc, z_0_0_calc = pos_0_0_calc
                logger.warning(f" [Grid calculation] {tool_name}: Calibration offset not found, using current offset")
            

            # Correct for end effector offset difference
            # Use actual calibrated position for correction
            if calib_position:
                # Actual position saved during calibration (calculated with calibration offset)
                x_0_0_actual = calib_position[0]
                y_0_0_actual = calib_position[1]
                

                # Apply position correction for gripper on MEA tools (X and Y)
                if end_effector == 'gripper' and 'mea' in tool_name.lower():
                    try:
                        position_offset = calib_manager.get_gripper_position_calibration(tool_name)
                        if position_offset is not None:
                            x_offset, y_offset = position_offset
                            x_0_0_actual = x_0_0_actual + x_offset
                            y_0_0_actual = y_0_0_actual + y_offset
                            logger.info(f" [Position correction] {tool_name}: Applied X correction value {x_offset:.2f}mm, Y correction value {y_offset:.2f}mm -> x_0_0_actual={x_0_0_actual:.2f}mm, y_0_0_actual={y_0_0_actual:.2f}mm")
                    except Exception as e:
                        logger.warning(f" [Position correction] {tool_name}: Position correction value load failed: {e}")
                

                # Calculate end effector offset difference (for debug)
                if calib_offset:
                    offset_error_x = x_0_0_actual - x_0_0_calc
                    offset_error_y = y_0_0_actual - y_0_0_calc
                    offset_error_distance = math.sqrt(offset_error_x**2 + offset_error_y**2)
                    

                    logger.info(f" [Calibration calculation] {tool_name} [0,0] position and end_effector offset correction:")
                    logger.info(f" - Calibration angles: angle1={angle1_0:.2f}°, angle2={angle2_0:.2f}°")
                    logger.info(f" - Forward Kinematics result (calibration offset): x={x_0_0_calc:.2f}, y={y_0_0_calc:.2f}")
                    logger.info(f" - Actual learned position (saved during calibration): x={x_0_0_actual:.2f}, y={y_0_0_actual:.2f}")
                    logger.info(f" - End Effector Offset error: Δx={offset_error_x:.3f}mm, Δy={offset_error_y:.3f}mm, distance={offset_error_distance:.3f}mm")
                else:
                    logger.info(f" [Calibration calculation] {tool_name} [0,0] position:")
                    logger.info(f" - Calibration angles: angle1={angle1_0:.2f}°, angle2={angle2_0:.2f}°")
                    logger.info(f" - Forward Kinematics result (current offset): x={x_0_0_calc:.2f}, y={y_0_0_calc:.2f}")
                    logger.info(f" - Actual learned position (saved during calibration): x={x_0_0_actual:.2f}, y={y_0_0_actual:.2f}")
                

                # Use corrected position (actual calibrated position)
                x_0_0_robot = x_0_0_actual
                y_0_0_robot = y_0_0_actual
            else:
                # Use calculated position if no calibration position available (no correction)
                logger.warning(" Calibration stored position not found, cannot correct end_effector offset")
                x_0_0_robot = x_0_0_calc
                y_0_0_robot = y_0_0_calc
                logger.info(f" [Calibration calculation] {tool_name} [0,0] position:")
                logger.info(f" - Calibration angles: angle1={angle1_0:.2f}°, angle2={angle2_0:.2f}°")
                logger.info(f" - Forward Kinematics result (robot coordinate system): x={x_0_0_robot:.2f}, y={y_0_0_robot:.2f}")
            

            # Calculate grid offset
            # Key: always calculate from (0,0) first, then add offset to target grid
            # This ensures consistent calculation whether moving sequentially or jumping to any grid cell
            grid_center_coords = grid_pattern.get('grid_center_coordinates', [])
            if grid_center_coords:
                # Calculate grid_index (row * cols + col)
                # tip box: 8 rows x 12 cols, mea: 8 rows x 2 cols
                if 'tip' in tool_name:
                    grid_cols = 12
                elif 'mea' in tool_name:
                    grid_cols = 2
                else:
                    grid_cols = 12  # Default
                

                grid_index = row * grid_cols + col
                

                if grid_index < len(grid_center_coords):
                    # Key: calculate (0,0) position first
                    # (0,0) position is already computed as x_0_0_robot, y_0_0_robot
                    

                    # Target grid position: add offset from (0,0) to target grid
                    # Use relative offset from grid_center_coordinates, based on (0,0)
                    grid_0_0_center = grid_center_coords[0]  # [0,0] position in grid_center_coordinates
                    target_grid_center = grid_center_coords[grid_index]  # Target position
                    

                    # Calculate relative offset from grid_center_coordinates
                    grid_offset_x = target_grid_center['x'] - grid_0_0_center['x']
                    grid_offset_y = target_grid_center['y'] - grid_0_0_center['y']
                    

                    # Verification: check that grid offset is correct in SCARA base frame
                    logger.info(f" [Grid calculation] {tool_name} Grid offset verification:")
                    logger.info(f" - [0,0] grid_center_coordinates (SCARA base): x={grid_0_0_center['x']:.2f}, y={grid_0_0_center['y']:.2f}")
                    logger.info(f" - Target [{row},{col}] grid_center_coordinates (SCARA base): x={target_grid_center['x']:.2f}, y={target_grid_center['y']:.2f}")
                    logger.info(f" - Grid offset (SCARA base): offset_x={grid_offset_x:.2f}, offset_y={grid_offset_y:.2f}")
                    logger.info(f" - Verify: target = [0,0] + offset = ({grid_0_0_center['x']:.2f} + {grid_offset_x:.2f}, {grid_0_0_center['y']:.2f} + {grid_offset_y:.2f}) = ({grid_0_0_center['x'] + grid_offset_x:.2f}, {grid_0_0_center['y'] + grid_offset_y:.2f})")
                    if abs((grid_0_0_center['x'] + grid_offset_x) - target_grid_center['x']) < 0.01 and \
                       abs((grid_0_0_center['y'] + grid_offset_y) - target_grid_center['y']) < 0.01:
                        logger.info(" - Grid offset verification passed")
                    else:
                        logger.warning(" - Grid offset verification failed: computed != target")
                    

                    # Apply grid offset based on actual taught position
                    if calib_position:
                        # Actual taught position (already stored in x_0_0_robot, y_0_0_robot)
                        grid_0_0_actual_x = calib_position[0]
                        grid_0_0_actual_y = calib_position[1]
                        

                        # Core: target = actual_taught[0,0] + grid_offset
                        # Use relative offset from grid_center_coordinates directly
                        # Calculation: target_actual = actual_learned[0,0] + grid_offset
                        #
                        # This applies grid offset based on (0,0) calibration position,
                        # then runs IK with current offset for accurate grid movement.
                        offset_x_robot = grid_offset_x
                        offset_y_robot = grid_offset_y
                        

                        logger.info(f" [Grid calculation] {tool_name} Grid offset calculation (using (0,0) SCARA base):")
                        logger.info(f" - [0,0] actual learned position (end effector tip): x={grid_0_0_actual_x:.2f}, y={grid_0_0_actual_y:.2f}")
                        logger.info(f" - Grid offset (relative distance): offset_x={grid_offset_x:.2f}, offset_y={grid_offset_y:.2f}")
                        logger.info(f" - Note: Grid offset is applied to (0,0) actual learned position")
                    else:
                        # Use distance if no calibration position
                        offset_x_robot = row * distance_x
                        offset_y_robot = col * distance_y
                        logger.warning(" No calibration position, using distance for grid offset")
                else:
                    # Use distance if no grid_center_coordinates
                    offset_x_robot = row * distance_x
                    offset_y_robot = col * distance_y
                    logger.warning(f" grid_index {grid_index} out of range, using distance")
            else:
                # Use distance if no grid_center_coordinates
                offset_x_robot = row * distance_x
                offset_y_robot = col * distance_y
                logger.warning(" grid_center_coordinates missing, using distance")
            

            # Target position (robot coordinate system)
            # Key: calculate from (0,0) first, then add offset to target grid
            # Ensures consistent calculation for both sequential and jump-to-grid moves
            #
            # Core: target = actual_taught[0,0] + grid_offset
            # (Grid relative distances are based on (0,0) position calculated with calibration offset)
            target_x_robot = x_0_0_robot + offset_x_robot
            target_y_robot = y_0_0_robot + offset_y_robot
            

            logger.info(f" [Grid calculation] {tool_name} Grid offset (using actual learned (0,0) as base):")
            logger.info(f" - Grid position: row={row}, col={col}, grid_index={grid_index}")
            logger.info(f" - [0,0] actual learned position (end effector tip): x={x_0_0_robot:.2f}, y={y_0_0_robot:.2f}")
            logger.info(f" - Target position (end effector tip): x={target_x_robot:.2f}, y={target_y_robot:.2f}")
            

            # IK for final angle calculation (iterative refinement to minimize error)
            # Key: target_x_robot/target_y_robot are based on calibration offset,
            # so IK must also use calibration offset for coordinate system consistency.
            #
            # Calculation steps:
            # 1. Target = actual_taught[0,0] + grid_offset
            #    (Grid relative distances are based on calibration offset (0,0))
            # 2. Run IK with calibration offset to find target angles
            # 3. Move to calculated angles
            #
            # Consistently using calibration offset ensures accurate grid movement.
            # IK uses calibration offset (because target was calculated based on it)
            if calib_offset:
                ik_solver = inv_kinematics(dx=calib_offset['x'], dy=calib_offset['y'], dz=calib_offset['z'])
                logger.info(f" [Grid calculation] {tool_name} ({action}): Using calibration offset for inverse kinematics: x={calib_offset['x']:.2f}, y={calib_offset['y']:.2f}, z={calib_offset['z']:.2f}")
            else:
                # Use current offset if no calibration offset
                ik_solver = inv_kinematics(dx=ee_offset['x'], dy=ee_offset['y'], dz=ee_offset['z'])
                logger.info(f" [Grid calculation] {tool_name} ({action}): Using current offset for IK: x={ee_offset['x']:.2f}, y={ee_offset['y']:.2f}, z={ee_offset['z']:.2f}")
            

            # Determine coordinate calculation mode per tool
            # Both take and apply are treated as pipette; handedness depends on tool_name
            effective_end_effector_for_handedness = 'pipette'  # mea2, mea-measure treated as pipette
            right_handed = self._determine_right_handed(effective_end_effector_for_handedness, tool_name)
            if right_handed is None:
                # mea-measure, mea2 are left-handed; others are right-handed
                if tool_name and tool_name.lower() in ['mea-measure', 'mea2']:
                    right_handed = False
                else:
                    right_handed = True
            logger.info(f" [Calibration calculation] Tool-specific coordinate calculation method: {'right-handed' if right_handed else 'left-handed'} (tool: {tool_name})")
            final_angles = ik_solver.inverse_kinematics_separated(target_x_robot, target_y_robot, 0, right_handed=right_handed)
            

            if final_angles:
                final_angle1, final_angle2, _ = final_angles
                

                # Iterative refinement: verify with forward_kinematics and correct error
                # Minimize round-trip errors from floating point arithmetic
                max_iterations = 3
                tolerance = 0.01  # Allow up to 0.01mm error
                

                for iteration in range(max_iterations):
                    # Run forward kinematics with current angles
                    actual_pos = ik_solver.forward_kinematics(final_angle1, final_angle2, 0)
                    actual_x, actual_y, _ = actual_pos
                    

                    # Calculate error from target position
                    error_x = target_x_robot - actual_x
                    error_y = target_y_robot - actual_y
                    error_distance = math.sqrt(error_x**2 + error_y**2)
                    

                    if error_distance < tolerance:
                        # Exit if error is within tolerance
                        logger.info(f" [Calibration calculation] Iterative refinement completed (iteration {iteration+1}):")
                        logger.info(f" - Final angles: angle1={final_angle1:.2f}°, angle2={final_angle2:.2f}°")
                        logger.info(f" - Actual position: x={actual_x:.3f}, y={actual_y:.3f}")
                        logger.info(f" - Target position: x={target_x_robot:.3f}, y={target_y_robot:.3f}")
                        logger.info(f" - Error: {error_distance:.4f}mm")
                        return float(final_angle1), float(final_angle2)
                    

                    # Correct target position and rerun IK
                    corrected_x = target_x_robot + error_x
                    corrected_y = target_y_robot + error_y
                    

                    logger.debug(f" [Calibration] iteration {iteration+1}: error={error_distance:.4f}mm, corrected=({corrected_x:.3f}, {corrected_y:.3f})")
                    

                    # Rerun IK with corrected position (using tool-specific coordinate mode)
                    refined_angles = ik_solver.inverse_kinematics_separated(corrected_x, corrected_y, 0, right_handed=right_handed)
                    if refined_angles:
                        final_angle1, final_angle2, _ = refined_angles
                    else:
                        # Use current result if IK fails
                        logger.warning(f" Inverse kinematics failed at iteration {iteration+1}, using current result")
                        break
                

                # Final result (error minimized after iterations)
                actual_pos = ik_solver.forward_kinematics(final_angle1, final_angle2, 0)
                actual_x, actual_y, _ = actual_pos
                final_error = math.sqrt((target_x_robot - actual_x)**2 + (target_y_robot - actual_y)**2)
                

                logger.info(f" [Calibration calculation] Final angles (after {max_iterations} iterations):")
                logger.info(f" - Final angles: angle1={final_angle1:.2f}°, angle2={final_angle2:.2f}°")
                logger.info(f" - Actual position: x={actual_x:.3f}, y={actual_y:.3f}")
                logger.info(f" - Target position: x={target_x_robot:.3f}, y={target_y_robot:.3f}")
                logger.info(f" - Final error: {final_error:.4f}mm")
                

                return float(final_angle1), float(final_angle2)
            else:
                logger.warning(f" Inverse kinematics failed: target=({target_x_robot:.2f}, {target_y_robot:.2f})")
                return None
                

        except Exception as e:
            logger.error(f" Grid angle calculation error: {e}")
            import traceback
            traceback.print_exc()
            return None
    

    def _execute_scara_movel(self, parameters: Dict[str, Any]) -> bool:
        """Execute SCARA movel_xyz command."""
        if not self.interface_manager.connected_interfaces['scara']:
            logger.error(" SCARA interface is not connected")
            return False
        

        try:
            xyzr = parameters.get('xyzr', [0, 0, 0, 0])
            speed = parameters.get('speed', 50)
            

            logger.info(f" SCARA linear movement: {xyzr} (speed: {speed})")
            

            # Skip gripper rotation if current end effector is pipette
            skip_gripper_rotation = (self.interface_manager.scara.current_end_effector == 'pipette')
            

            result = self.interface_manager.scara.movel_xyz(
                goal_x=xyzr[0], goal_y=xyzr[1], goal_z=xyzr[2],
                goal_r=xyzr[3], speed=speed,
                skip_gripper_rotation=skip_gripper_rotation
            )
            

            return result.get('success', False)
            

        except Exception as e:
            logger.error(f" SCARA linear move error: {e}")
            return False
    

    def _execute_scara_move_to_top(self, parameters: Dict[str, Any]) -> bool:
        """Execute SCARA move_to_top command."""
        if not self.interface_manager.connected_interfaces['scara']:
            logger.error(" SCARA interface is not connected")
            return False
        

        try:
            # Check end effector (gripper rotation is auto-skipped for pipette)
            end_effector = parameters.get('end_effector', 'pipette')
            # Note: move_to_top updates state automatically; direct update not needed
            # (existing code still works - redundant but harmless)
            # if end_effector != self.interface_manager.scara.current_end_effector:
            #     logger.info(f'[move_to_top] end_effector update: {self.interface_manager.scara.current_end_effector} -> {end_effector}')
            # self.interface_manager.scara.current_end_effector = end_effector
            

            # Use configured speed if not specified in parameters
            speed = parameters.get('speed')
            if speed is None:
                speed = getattr(self, 'initial_position_move_to_top_speed', 50)
            

            # For gripper at mea1/mea3: apply slow speed within 70mm zone from floor
            if end_effector == 'gripper':
                # Use normal speed immediately after place action
                command_type = parameters.get('type', '')
                is_place_after = (command_type == 'place')
                

                if is_place_after:
                    logger.info(" [move_to_top] After place action - using normal speed")
                    logger.info(f" - Speed: {speed:.1f}mm/s (keeping current setting)")
                else:
                    try:
                        # Use end-effector-offset-corrected position for accurate zone determination
                        current_pos = self.interface_manager.scara.get_current_position(include_end_effector=True)
                        if current_pos:
                            current_x = current_pos.get('x')
                            current_y = current_pos.get('y')
                            # Use ee_z if available, otherwise use robot Z
                            current_z = current_pos.get('ee_z') if current_pos.get('ee_z') is not None else current_pos.get('z')
                            

                            # Identify mea1/mea3 by X, Y coordinate ranges
                            # mea1: center_coordinates: {"x": 234.5, "y": -144.8}
                            # mea3: center_coordinates: {"x": 234.5, "y": -274.5}
                            # mea storage size: {"x": 83, "y": 34}
                            # X range: 234.5 +/- 41.5 = 193.0 ~ 276.0
                            # mea1 Y range: -144.8 +/- 17 = -161.8 ~ -127.8
                            # mea3 Y range: -274.5 +/- 17 = -291.5 ~ -257.5
                            check_location = None
                            if 193.0 <= current_x <= 276.0:
                                if -161.8 <= current_y <= -127.8:
                                    check_location = 'mea1'
                                elif -291.5 <= current_y <= -257.5:
                                    check_location = 'mea3'
                            

                            if check_location in ['mea1', 'mea3']:
                                # Dynamically create height_calculator if not present
                                if not hasattr(self, 'height_calculator') or self.height_calculator is None:
                                    if hasattr(self, 'stack_manager') and self.stack_manager:
                                        try:
                                            import sys
                                            import os
                                            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                                            if project_root not in sys.path:
                                                sys.path.insert(0, project_root)
                                            from utils.mea_height_calculator import MEAHeightCalculator
                                            self.height_calculator = MEAHeightCalculator(self.stack_manager)
                                        except Exception as e:
                                            logger.warning(f" MEAHeightCalculator creation failed: {e}")
                                            self.height_calculator = None
                                

                                if hasattr(self, 'height_calculator') and self.height_calculator:
                                    base_z = self.height_calculator.get_tool_center_z(check_location)
                                    mea_height = self.height_calculator.mea_height
                                    if base_z is not None:
                                        # Calculate floor: base_z - mea_height
                                        floor_z = base_z - mea_height
                                        # 70mm from floor = floor_z + 70
                                        threshold_z = floor_z + 70.0
                                        

                                        # move_to_top moves to Z=0; if currently inside zone, use two-stage
                                        # Stage 1: current -> zone boundary (threshold_z) - slow
                                        # Stage 2: zone boundary -> Z=0 - normal speed
                                        if floor_z <= current_z <= threshold_z:
                                            # Current position inside zone: use two-stage move
                                            mea_storage_speed = getattr(self, 'mea_storage_internal_speed', 10.0)
                                            logger.info(f" [move_to_top] {check_location}: two-stage move needed (starting from inside zone)")
                                            logger.info(f" - Current position: X={current_x:.2f}, Y={current_y:.2f}, Z={current_z:.2f}mm (inside zone)")
                                            logger.info(f" - Zone boundary: Z={threshold_z:.2f}mm")
                                            logger.info(" - Target position: Z=0mm (outside zone, above)")
                                            logger.info(f" - Floor (floor_z): {floor_z:.2f}mm")
                                            logger.info(f" - 70mm from floor (threshold_z): {threshold_z:.2f}mm")
                                            

                                            # Stage 1: current -> zone boundary (threshold_z) - slow
                                            logger.info(f" [move_to_top] Stage 1: current → zone boundary (speed: {mea_storage_speed:.1f}mm/s)")
                                            

                                            # Move to zone boundary using move_offset
                                            offset_to_threshold = threshold_z - current_z
                                            result1 = self.interface_manager.scara.move_offset(
                                                'z', offset_to_threshold, mea_storage_speed, skip_gripper_rotation=True
                                            )
                                            

                                            if not result1:
                                                logger.error(f" Step 1 movement failed")
                                                return False
                                            

                                            logger.info(f" [move_to_top] Stage 1 done: zone boundary reached (Z={threshold_z:.2f}mm)")
                                            

                                            # Stage 2: zone boundary -> Z=0 - normal speed
                                            logger.info(f" [move_to_top] Stage 2: zone boundary → Z=0 (speed: {speed:.1f}mm/s)")
                                            

                                            # Update current position (with end effector offset)
                                            current_pos_after = self.interface_manager.scara.get_current_position(include_end_effector=True)
                                            if current_pos_after:
                                                current_z_after = current_pos_after.get('ee_z') if current_pos_after.get('ee_z') is not None else current_pos_after.get('z')
                                                # move_to_top targets ee Z=0; calculate using ee coordinates
                                                offset_to_top = 0 - current_z_after
                                                

                                                result2 = self.interface_manager.scara.move_offset(
                                                    'z', offset_to_top, speed, skip_gripper_rotation=True
                                                )
                                                

                                                if not result2:
                                                    logger.error(f" Step 2 movement failed")
                                                    return False
                                                

                                                logger.info(" [move_to_top] Stage 2 done: Z=0 reached")
                                                return True
                                            else:
                                                logger.error(" Cannot get current position")
                                                return False
                                        elif current_z < floor_z:
                                            # Current position outside zone (below): use normal speed
                                            logger.info(f" [move_to_top] {check_location}: starting outside zone (using current speed)")
                                            logger.info(f" - Current position: Z={current_z:.2f}mm < floor_z ({floor_z:.2f}mm)")
                                            logger.info(f" - Speed: {speed:.1f}mm/s (keeping current setting)")
                                        elif current_z > threshold_z:
                                            # Current position outside zone (above): use normal speed
                                            logger.info(f" [move_to_top] {check_location}: starting outside zone (above), using current speed")
                                            logger.info(f" - Current position: Z={current_z:.2f}mm > threshold_z ({threshold_z:.2f}mm)")
                                            logger.info(" - Target position: Z=0mm (outside zone, above)")
                                            logger.info(f" - Floor (floor_z): {floor_z:.2f}mm")
                                            logger.info(f" - 70mm from floor (threshold_z): {threshold_z:.2f}mm")
                                            logger.info(f" - Speed: {speed:.1f}mm/s (keeping current, not crossing zone)")
                    except Exception as e:
                        logger.warning(f" [move_to_top] Error checking mea storage speed: {e}")
                        # Fall back to normal move_to_top on error
            

            # Run normal move_to_top only if two-stage move was not completed
            # (Two-stage move already returned True if completed)
            logger.info(f" Moving SCARA to top position... (speed: {speed}, end_effector: {end_effector})")
            

            # Execute SCARA move to top command
            result = self.interface_manager.scara.move_to_top(speed=speed)
            

            return result
            

        except Exception as e:
            logger.error(f" SCARA move to top error: {e}")
            return False
    

    def _execute_scara_move_offset(self, parameters: Dict[str, Any]) -> bool:
        """Execute SCARA move_offset command."""
        if not self.interface_manager.connected_interfaces['scara']:
            logger.error(" SCARA interface is not connected")
            return False
        

        try:
            axis = parameters.get('axis', 'x')
            offset = parameters.get('offset', 0)
            speed_from_params = parameters.get('speed', 20)
            speed = speed_from_params


            # Apply low speed for short X/Y moves (within threshold)
            short_distance_threshold = self.config_manager.get("threshold", "short_distance_threshold") if self.config_manager else 20
            logger.info(f" [DEBUG] move_offset condition check: axis={axis}, offset={offset}, abs(offset)={abs(offset)}, speed_from_params={speed_from_params}")
            if axis in ['x', 'y'] and abs(offset) <= short_distance_threshold:
                speed = self.move_offset_low_speed
                logger.info(f" [DEBUG] move_offset low speed applied: axis={axis}, offset={offset}, speed={speed}")
            else:
                logger.info(f" [DEBUG] move_offset keeping normal speed: axis={axis}, offset={offset}, speed={speed}")


            # For Z-axis with gripper: check mea1/mea3 slow zone and apply two-stage if needed
            if axis == 'z' and self.interface_manager.scara.current_end_effector == 'gripper':
                try:
                    # Use end-effector-offset-corrected position for accurate zone determination
                    current_pos = self.interface_manager.scara.get_current_position(include_end_effector=True)
                    if current_pos:
                        current_x = current_pos.get('x')
                        current_y = current_pos.get('y')
                        # Use ee_z if available, otherwise use robot Z
                        current_ee_z = current_pos.get('ee_z') if current_pos.get('ee_z') is not None else current_pos.get('z')
                        

                        # Calculate target Z (end effector coordinate system)
                        # move_offset considers end effector offset; use current ee Z as base
                        target_ee_z = current_ee_z + offset
                        

                        # Identify mea1/mea3 by X, Y coordinate ranges
                        # mea1: center_coordinates: {"x": 234.5, "y": -144.8}
                        # mea3: center_coordinates: {"x": 234.5, "y": -274.5}
                        # mea storage size: {"x": 83, "y": 34}
                        # X range: 234.5 +/- 41.5 = 193.0 ~ 276.0
                        # mea1 Y range: -144.8 +/- 17 = -161.8 ~ -127.8
                        # mea3 Y range: -274.5 +/- 17 = -291.5 ~ -257.5
                        check_location = None
                        if 193.0 <= current_x <= 276.0:
                            if -161.8 <= current_y <= -127.8:
                                check_location = 'mea1'
                            elif -291.5 <= current_y <= -257.5:
                                check_location = 'mea3'
                        

                        if check_location in ['mea1', 'mea3']:
                            # Dynamically create height_calculator if not present
                            if not hasattr(self, 'height_calculator') or self.height_calculator is None:
                                if hasattr(self, 'stack_manager') and self.stack_manager:
                                    try:
                                        import sys
                                        import os
                                        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                                        if project_root not in sys.path:
                                            sys.path.insert(0, project_root)
                                        from utils.mea_height_calculator import MEAHeightCalculator
                                        self.height_calculator = MEAHeightCalculator(self.stack_manager)
                                    except Exception as e:
                                        logger.warning(f" MEAHeightCalculator creation failed: {e}")
                                        self.height_calculator = None
                            

                            if hasattr(self, 'height_calculator') and self.height_calculator:
                                base_z = self.height_calculator.get_tool_center_z(check_location)
                                mea_height = self.height_calculator.mea_height
                                if base_z is not None:
                                    # Calculate floor: base_z - mea_height
                                    floor_z = base_z - mea_height
                                    # 70mm from floor = floor_z + 70
                                    threshold_z = floor_z + 70.0
                                    

                                    # Analyze movement path considering both current and target positions
                                    # move_offset uses end effector coordinate system for Z judgment
                                    current_in_range = floor_z <= current_ee_z <= threshold_z
                                    target_in_range = floor_z <= target_ee_z <= threshold_z
                                    

                                    # Two-stage split flag
                                    need_two_stage = False
                                    

                                    if target_in_range and not current_in_range:
                                        # Case: current outside, target inside -> two-stage move
                                        need_two_stage = True
                                        logger.info(f" [move_offset] {check_location}: two-stage move needed (zone entry)")
                                        logger.info(f" - Current position: Z={current_ee_z:.2f}mm (outside zone)")
                                        logger.info(f" - Zone boundary: Z={threshold_z:.2f}mm")
                                        logger.info(f" - Target position: Z={target_ee_z:.2f}mm (offset: {offset:.2f}mm, zone: {floor_z:.2f}mm ~ {threshold_z:.2f}mm)")
                                        

                                        # Stage 1: current -> zone boundary (threshold_z) - normal speed
                                        offset_to_threshold = threshold_z - current_ee_z
                                        logger.info(f" [move_offset] Stage 1: current → zone boundary (speed: {speed:.1f}mm/s, offset: {offset_to_threshold:.2f}mm)")
                                        

                                        result1 = self.interface_manager.scara.move_offset(
                                            'z', offset_to_threshold, speed, skip_gripper_rotation=True
                                        )
                                        

                                        if not result1:
                                            logger.error(f" Step 1 movement failed")
                                            return False
                                        

                                        logger.info(f" [move_offset] Stage 1 done: zone boundary reached (Z={threshold_z:.2f}mm)")
                                        

                                        # Stage 2: zone boundary -> target at mea_storage_internal_speed
                                        mea_storage_speed = getattr(self, 'mea_storage_internal_speed', 10.0)
                                        offset_to_target = target_ee_z - threshold_z
                                        logger.info(f" [move_offset] Stage 2: zone boundary → target (speed: {mea_storage_speed:.1f}mm/s, offset: {offset_to_target:.2f}mm)")
                                        

                                        result2 = self.interface_manager.scara.move_offset(
                                            'z', offset_to_target, mea_storage_speed, skip_gripper_rotation=True
                                        )
                                        

                                        if not result2:
                                            logger.error(f" Step 2 movement failed")
                                            return False
                                        

                                        logger.info(f" [move_offset] Stage 2 done: target reached (Z={target_ee_z:.2f}mm)")
                                        logger.info(f" - Floor (floor_z): {floor_z:.2f}mm")
                                        logger.info(f" - 70mm from floor (threshold_z): {threshold_z:.2f}mm")
                                        return True
                                    elif target_in_range and current_in_range:
                                        # Case: both inside zone -> slow speed throughout
                                        original_speed = speed
                                        mea_storage_speed = getattr(self, 'mea_storage_internal_speed', 10.0)
                                        speed = mea_storage_speed
                                        logger.info(f" [move_offset] {check_location}: moving inside zone (speed {speed:.1f} applied)")
                                        logger.info(f" - Current position: Z={current_ee_z:.2f}mm (inside zone)")
                                        logger.info(f" - Target position: Z={target_ee_z:.2f}mm (inside zone)")
                                        logger.info(f" - Speed adjustment: {original_speed:.1f} → {speed:.1f}mm/s")
                                    elif current_in_range and target_ee_z < floor_z:
                                        # Case: current inside, target outside(below) -> slow until zone exit
                                        # Two-stage: current -> floor_z (slow), floor_z -> target (normal)
                                        need_two_stage = True
                                        mea_storage_speed = getattr(self, 'mea_storage_internal_speed', 10.0)
                                        logger.info(f" [move_offset] {check_location}: two-stage move needed (zone exit)")
                                        logger.info(f" - Current position: Z={current_ee_z:.2f}mm (inside zone)")
                                        logger.info(f" - Zone boundary: Z={floor_z:.2f}mm")
                                        logger.info(f" - Target position: Z={target_ee_z:.2f}mm (outside zone, below)")
                                        

                                        # Stage 1: current -> zone boundary (floor_z) - slow
                                        offset_to_floor = floor_z - current_ee_z
                                        logger.info(f" [move_offset] Stage 1: current → zone boundary (speed: {mea_storage_speed:.1f}mm/s, offset: {offset_to_floor:.2f}mm)")
                                        

                                        result1 = self.interface_manager.scara.move_offset(
                                            'z', offset_to_floor, mea_storage_speed, skip_gripper_rotation=True
                                        )
                                        

                                        if not result1:
                                            logger.error(f" Step 1 movement failed")
                                            return False
                                        

                                        logger.info(f" [move_offset] Stage 1 done: zone boundary reached (Z={floor_z:.2f}mm)")
                                        

                                        # Stage 2: zone boundary -> target - normal speed
                                        offset_to_target = target_ee_z - floor_z
                                        logger.info(f" [move_offset] Stage 2: zone boundary → target (speed: {speed:.1f}mm/s, offset: {offset_to_target:.2f}mm)")
                                        

                                        result2 = self.interface_manager.scara.move_offset(
                                            'z', offset_to_target, speed, skip_gripper_rotation=True
                                        )
                                        

                                        if not result2:
                                            logger.error(f" Step 2 movement failed")
                                            return False
                                        

                                        logger.info(f" [move_offset] Stage 2 done: target reached (Z={target_ee_z:.2f}mm)")
                                        return True
                                    elif target_ee_z > threshold_z:
                                        logger.info(f" [move_offset] {check_location}: zone 70mm+ from floor (using current speed)")
                                        logger.info(f" - Current position: Z={current_ee_z:.2f}mm")
                                        logger.info(f" - Target position: Z={target_ee_z:.2f}mm > threshold_z ({threshold_z:.2f}mm)")
                                        logger.info(f" - Speed: {speed:.1f}mm/s (keeping current setting)")
                except Exception as e:
                    logger.warning(f" [move_offset] Error checking mea storage speed: {e}")


            logger.info(f" SCARA offset movement: {axis} -> {offset} (speed: {speed})")
            

            # Skip gripper rotation if current end effector is pipette
            skip_gripper_rotation = (self.interface_manager.scara.current_end_effector == 'pipette')
            

            # Execute SCARA offset move command
            result = self.interface_manager.scara.move_offset(axis, offset, speed, skip_gripper_rotation=skip_gripper_rotation)
            

            return result
            

        except Exception as e:
            logger.error(f" SCARA offset move error: {e}")
            return False
    

    def _execute_daken_check_tip(self, parameters: Dict[str, Any]) -> bool:
        """Execute DAKEN check_tip command."""
        if not self.interface_manager.connected_interfaces['daken']:
            logger.error(" DAKEN interface not connected")
            return False
        

        try:
            logger.info(" Checking DAKEN tip...")
            

            # Execute DAKEN tip check command
            result = self.interface_manager.daken.check_tip()
            

            if result == "01":
                logger.info(" Tip is properly mounted")
                return True
            elif result == "02":
                logger.warning(" No tip")
                return False
            elif result == "03":
                logger.error(" Tip check error")
                return False
            else:
                logger.warning(f" Unknown tip status: {result}")
                return False
                

        except Exception as e:
            logger.error(f" DAKEN tip check error: {e}")
            return False
    

    def _execute_daken_aspirate(self, parameters: Dict[str, Any]) -> bool:
        """Execute DAKEN aspirate_liquid command."""
        if not self.interface_manager.connected_interfaces['daken']:
            logger.error(" DAKEN interface not connected")
            return False
        

        try:
            amount = parameters.get('amount', self.aspiration_amount_default)
            source_id = parameters.get('source_id')  # source3, source1, etc. or None (MEA tool etc.)
            

            # Add 30uL for take actions
            is_take = self._is_take_action(parameters)
            aspirate_amount = amount + 30 if is_take else amount
            

            logger.info(f"DAKEN liquid aspiration: {amount}uL (source: {source_id})" + (f" -> {aspirate_amount}uL (take action: +30uL)" if is_take else ""))
            

            # Use Tube Interface only when source_id is provided (SOURCE tool)
            if self.tube_interface and source_id:
                self._handle_tube_operations_with_source_id(source_id, amount)
                # Aspiration with Tube Interface (surface detection and synchronized descent)
                # Descent distance uses original amount; actual aspiration uses aspirate_amount
                # aspirate_amount already calculated based on is_take; pass as-is
                aspiration_success = self._perform_aspiration_surface_detection(source_id, amount, aspirate_amount=aspirate_amount)
                # Store source_id of last take action (for 30uL dispense decision in dispose action)
                if aspiration_success:
                    self.last_take_source_id = source_id
                

                # Post-aspiration: additional steps after successful aspiration
                if aspiration_success:
                    try:
                        # 1. Read current Z position
                        current_pos = self.interface_manager.scara.get_current_position()
                        if current_pos is None:
                            logger.warning(" Cannot read current position, skipping additional task")
                            return aspiration_success
                        

                        current_z = current_pos['z']
                        # Recalculate in pipette+tip coordinate frame
                        ee_offset = self.interface_manager.scara.get_end_effector_offset('pipette', with_tip=True)
                        current_z_ee = current_z + ee_offset['z']
                        logger.info(f" [Additional task] Current Z (pipette + tip frame): {current_z_ee:.2f}mm")
                        

                        # 2. Load tool info from table_coordinates.json
                        import json
                        from pathlib import Path
                        

                        table_coords_path = Path("table_coordinates.json")
                        if not table_coords_path.exists():
                            logger.warning(" table_coordinates.json not found, skipping additional task")
                            return aspiration_success
                        

                        with open(table_coords_path, 'r', encoding='utf-8') as f:
                            table_coords = json.load(f)
                        

                        tool_name = source_id.lower()  # source1, source2, etc.
                        tool_data = table_coords.get('tools', {}).get(tool_name)
                        if not tool_data:
                            logger.warning(f" {tool_name} tool info not found, skipping additional task")
                            return aspiration_success
                        

                        # Read tool center Z and size Z
                        center_coords = tool_data.get('center_coordinates', {})
                        tool_center_z = center_coords.get('z')  # Robot coordinate system
                        size = tool_data.get('size', {})
                        tool_size_z = size.get('z', 0)
                        

                        if tool_center_z is None:
                            logger.warning(f" {tool_name} center_coordinates.z not found, skipping additional task")
                            return aspiration_success
                        

                        logger.info(f" [Additional task] Tool info: {tool_name}")
                        logger.info(f" - tool_center_z: {tool_center_z:.2f}mm")
                        logger.info(f" - tool_size_z: {tool_size_z:.2f}mm")
                        

                        # 3. Calculate tube top position (tool_center_z is already tube top)
                        tool_top_z = tool_center_z
                        # Read offset value from settings
                        aspiration_post_z_offset = getattr(self, 'aspiration_post_z_offset', 1.0)
                        target_z = tool_top_z - aspiration_post_z_offset  # tube top - offset
                        logger.info(f" [Additional task] Tool top Z: {tool_top_z:.2f}mm, Z offset: {aspiration_post_z_offset:.2f}mm (config)")
                        

                        # Convert to pipette+tip coordinate frame (consider end effector offset)
                        target_z_robot = target_z - ee_offset['z']
                        current_z_robot = current_z
                        

                        # 4. Move Z to tube top minus offset
                        # Note: z_offset is already in robot coordinate system,
                        # use move_linear instead of move_offset to prevent double offset application
                        z_offset = target_z_robot - current_z_robot
                        logger.info(f" [Additional task] Z move: {z_offset:.2f}mm (target: {target_z:.2f}mm, pipette + tip frame)")
                        logger.info(f" [Additional task] Robot frame move: current_z={current_z_robot:.2f}mm -> target_z={target_z_robot:.2f}mm")
                        

                        if abs(z_offset) > 0.01:  # Move only if difference > 0.01mm
                            # Use move_linear (specify robot coordinate system to prevent double offset)
                            result = self.interface_manager.scara.move_linear(
                                current_pos['x'],
                                current_pos['y'],
                                target_z_robot,  # Already converted to robot coordinate system
                                current_pos['r'],
                                speed=10.0,
                                skip_gripper_rotation=True,
                                use_end_effector_coordinate=False  # Use robot coordinate system
                            )
                            if not result:
                                logger.warning(" Z move failed, skipping additional task")
                                return aspiration_success
                            

                            # Wait for move completion
                            if not self.interface_manager.scara.wait_for_movement_complete(timeout=self.movement_completion_timeout, action_commander=self.action_commander):
                                logger.warning(" Z move completion wait timeout, continuing")
                            

                            # Re-read position after Z move (for correct Z value in X axis move)
                            current_pos_after_z = self.interface_manager.scara.get_current_position()
                            if current_pos_after_z:
                                current_pos = current_pos_after_z
                                logger.info(f" [Additional task] Position after Z move: Z={current_pos['z']:.2f}mm")
                        else:
                            logger.info(" Z move not needed (already at target)")
                        

                        # 5. Calculate tool radius and move X axis
                        tool_radius = None
                        if 'dia' in size:
                            tool_radius = size.get('dia', 0) / 2.0
                        elif 'x' in size:
                            tool_radius = size.get('x', 0) / 2.0
                        else:
                            logger.warning(f" {tool_name} radius not found, using default 10mm")
                            tool_radius = 10.0
                        

                        # Read offset value from settings
                        aspiration_post_x_offset = getattr(self, 'aspiration_post_x_offset', 2.0)
                        x_offset = tool_radius - aspiration_post_x_offset  # radius - offset
                        logger.info(f" [Additional task] Tool radius: {tool_radius:.2f}mm, X offset: {aspiration_post_x_offset:.2f}mm (config), X move: {x_offset:.2f}mm")
                        

                        # Note: x_offset is based on tool physical radius (robot coordinate system)
                        # use move_linear instead of move_offset to prevent double offset application
                        if abs(x_offset) > 0.01:  # Move only if difference > 0.01mm
                            # Use move_linear (specify robot coordinate system)
                            result = self.interface_manager.scara.move_linear(
                                current_pos['x'] + x_offset,  # Robot coordinate system
                                current_pos['y'],
                                current_pos['z'],  # Use Z position updated after Z move
                                current_pos['r'],
                                speed=5.0,
                                skip_gripper_rotation=True,
                                use_end_effector_coordinate=False  # Use robot coordinate system
                            )
                            if not result:
                                logger.warning(" X move failed, skipping additional task")
                                return aspiration_success
                            

                            # Wait for move completion
                            if not self.interface_manager.scara.wait_for_movement_complete(timeout=self.movement_completion_timeout, action_commander=self.action_commander):
                                logger.warning(" X-axis move completion wait timeout, continuing")
                            

                            # Wait 0.2 seconds
                            logger.info(" Waiting 1 second...")
                            time.sleep(0.2)
                        else:
                            logger.info(" X-axis move not needed (already at target position)")
                            time.sleep(0.2)
                        

                        # 6. spit 30 uL
                        logger.info(" Dispensing 30μL...")
                        spit_result = self.interface_manager.daken.spit_liquid(30)
                        if spit_result == "01":
                            logger.info(" 30μL dispense completed")
                        else:
                            logger.warning(f" 30μL dispense failed: status code {spit_result}")
                        

                        # 7. Return X axis (return to tube center after dispense)
                        if abs(x_offset) > 0.01:  # Return only if X axis was moved
                            # Read current position after dispense
                            current_pos_after_spit = self.interface_manager.scara.get_current_position()
                            if current_pos_after_spit:
                                logger.info(f" [Additional task] X-axis return move: -{x_offset:.2f}mm (return to tool center)")
                                # Move in reverse direction (negative offset)
                                result = self.interface_manager.scara.move_linear(
                                    current_pos_after_spit['x'] - x_offset,  # Reverse (robot coordinate)
                                    current_pos_after_spit['y'],
                                    current_pos_after_spit['z'],
                                    current_pos_after_spit['r'],
                                    speed=5.0,
                                    skip_gripper_rotation=True,
                                    use_end_effector_coordinate=False  # Use robot coordinate system
                                )
                                if not result:
                                    logger.warning(" X return move failed, continuing")
                                else:
                                    # Wait for move completion
                                    if not self.interface_manager.scara.wait_for_movement_complete(timeout=self.movement_completion_timeout, action_commander=self.action_commander):
                                        logger.warning(" X return move completion wait timeout, continuing")
                                    logger.info(" X return move done (returned to tool center)")
                            else:
                                logger.warning(" Cannot read position after dispense, skipping X return")
                        

                    except Exception as e:
                        logger.error(f" Error during additional task: {e}")
                        import traceback
                        logger.error(traceback.format_exc())
                        # Post-aspiration failure does not affect aspiration success
                

                return aspiration_success
            else:
                # No source_id (MEA tool etc.): direct aspiration only
                logger.info(f" Direct aspiration from MEA tool etc. (no source_id)")
                result = self.interface_manager.daken.aspirate_liquid(aspirate_amount)
                if result == "01":
                    logger.info(f" DAKEN aspiration completed: {amount}μL")
                    return True
                else:
                    logger.error(f" DAKEN aspiration failed: status {result}")
                    return False
                

        except Exception as e:
            logger.error(f" DAKEN liquid aspiration error: {e}")
            return False
    

    def _execute_daken_spit(self, parameters: Dict[str, Any]) -> bool:
        """Execute DAKEN spit_liquid command."""
        if not self.interface_manager.connected_interfaces['daken']:
            logger.error(" DAKEN interface not connected")
            return False
        

        try:
            #air_amount = parameters.get('air_amount', 15)
            amount = parameters.get('amount', self.spit_amount_default)
            tool_name = parameters.get('tool_name')  # For MEA tool check
            

            # Use last_tool_name if tool_name not provided (same as move_z_position)
            if not tool_name:
                if hasattr(self, 'last_tool_name') and self.last_tool_name:
                    tool_name = self.last_tool_name
                    logger.info(f" [spit] No tool_name, using last_tool_name: {tool_name}")
            

            logger.info(f" DAKEN liquid dispensing: {amount}μL")
            

            # Check if MEA tool
            is_mea_tool = tool_name and 'mea' in tool_name.lower()


            # For Angled Pipette (mea2/mea-measure) apply action:
            # Move end effector along its direction before dispensing
            # Only for apply action (take action uses Pipette with tip)
            # Condition: pipette end effector, apply action, tool_name is mea2 or mea-measure
            action = parameters.get('action') or parameters.get('type')  # 'apply' or 'take'
            current_end_effector = self.interface_manager.scara.current_end_effector
            

            # Debug: check conditions
            logger.info(" [spit] Condition check:")
            logger.info(f" - tool_name: {tool_name}")
            logger.info(f" - action: {action}")
            logger.info(f" - current_end_effector: {current_end_effector}")
            logger.info(f" - parameters keys: {list(parameters.keys())}")
            

            is_angled_pipette_mea = self._is_angled_pipette_mode('pipette', tool_name, current_end_effector)
            logger.info(f" - is_angled_pipette_mea: {is_angled_pipette_mea}")
            logger.info(f" - action == 'apply': {action == 'apply'}")
            logger.info(f" - Condition (action == 'apply' and is_angled_pipette_mea): {action == 'apply' and is_angled_pipette_mea}")
            

            # Execute directional move only for apply action
            if action == 'apply' and is_angled_pipette_mea:
                try:
                    # Read current angles before spit_liquid
                    # Get offset value from settings
                    if self.config_manager:
                        _offset = self.config_manager.get("offset_distance", "angled_pipette_offset") or 2.0
                    else:
                        _offset = 2.0  # Default value
                    

                    # Brief wait for position to stabilize after move_z_position
                    # Re-read position after short delay
                    time.sleep(0.2)  # Wait 200ms
                    

                    # Read actual encoder Z for better accuracy
                    self.interface_manager.scara.robot.get_encoder_coor()
                    actual_robot_z = self.interface_manager.scara.robot.encoder_z
                    

                    current_pos = self.interface_manager.scara.get_current_position()
                    if current_pos:
                        current_angle1 = current_pos.get('angle1', 0)
                        current_angle2 = current_pos.get('angle2', 0)
                        current_robot_z_from_pos = current_pos.get('z', 0)
                        

                        # Prefer actual encoder Z
                        # Use encoder Z if it differs from get_current_position
                        if abs(current_robot_z_from_pos - actual_robot_z) > 0.5:
                            logger.warning(f" [Angled Pipette - before spit] get_current_position() Z ({current_robot_z_from_pos:.2f}mm) != encoder Z ({actual_robot_z:.2f}mm). Using encoder.")
                            current_robot_z = actual_robot_z
                        else:
                            current_robot_z = current_robot_z_from_pos
                        

                        logger.info(f" [Angled Pipette - before spit] Current robot Z: {current_robot_z:.2f}mm (encoder: {actual_robot_z:.2f}mm, get_current_position: {current_robot_z_from_pos:.2f}mm)")
                        

                        # Determine coordinate mode (left-handed/right-handed) per tool
                        # Recalculate right_handed after reading angles (same as settings_window)
                        # Ensures mea2/mea-measure get correct left-handed values
                        effective_end_effector = 'pipette'  # mea2, mea-measure always treated as pipette
                        right_handed = self._determine_right_handed(effective_end_effector, tool_name)
                        if right_handed is None:
                            # mea-measure, mea2 are left-handed; others are right-handed
                            if tool_name and tool_name.lower() in ['mea-measure', 'mea2']:
                                right_handed = False
                            else:
                                right_handed = True
                        

                        # Calculate end effector direction angle
                        # Right-handed: angle1 + angle2
                        # Left-handed: angle1 + angle2 - 90 degrees (bent 90 degrees inward)
                        if right_handed:
                            # Right-handed: angle1 + angle2
                            end_effector_angle_deg = current_angle1 + current_angle2
                        else:
                            # Left-handed: angle1 + angle2 - 90 degrees
                            end_effector_angle_deg = current_angle1 + current_angle2 - 90.0
                        

                        end_effector_angle_rad = math.radians(end_effector_angle_deg)
                        

                        # Calculate X, Y offset along end effector direction using trigonometry
                        # X axis: cos, Y axis: sin (SCARA robot coordinate system)
                        offset_x = _offset * math.cos(end_effector_angle_rad)
                        offset_y = _offset * math.sin(end_effector_angle_rad)
                        

                        logger.info(f" [Angled Pipette - before spit] Current angles: angle1={current_angle1:.2f}°, angle2={current_angle2:.2f}°")
                        logger.info(f" [Angled Pipette - before spit] Coordinate mode: {'right-handed' if right_handed else 'left-handed'}")
                        logger.info(f" [Angled Pipette - before spit] End effector direction: {end_effector_angle_deg:.2f}° (base: {current_angle1 + current_angle2:.2f}° {'+ 0' if right_handed else '- 90'}°)")
                        logger.info(f" [Angled Pipette - before spit] {_offset}mm move: x_offset={offset_x:.3f}mm, y_offset={offset_y:.3f}mm")
                        

                        # For Angled Pipette (mea2/mea-measure) apply action: use with_tip=False
                        # Get current end effector tip position (end effector coordinate system)
                        from ikine2 import inv_kinematics
                        # For apply action: always use with_tip=False for pipette_with_tip_15degree offset
                        ee_offset = self.interface_manager.scara.get_end_effector_offset(
                            effective_end_effector,
                            False,  # Explicitly set False to use pipette_with_tip_15degree
                            tool_name
                        )
                        ik_solver = inv_kinematics(dx=ee_offset['x'], dy=ee_offset['y'], dz=ee_offset['z'])
                        # Use actual robot Z value
                        current_ee_pos = ik_solver.forward_kinematics(current_angle1, current_angle2, current_robot_z)
                        current_ee_x, current_ee_y, current_ee_z = current_ee_pos
                        

                        logger.info(" [Angled Pipette - before spit] Current end effector tip position:")
                        logger.info(f" - Robot Z: {current_robot_z:.2f}mm")
                        logger.info(f" - End effector offset (with_tip=False): {ee_offset}")
                        logger.info(f" - Computed end effector tip: x={current_ee_x:.2f}mm, y={current_ee_y:.2f}mm, z={current_ee_z:.2f}mm")
                        

                        # Target end effector tip position (apply X,Y offset; keep Z)
                        target_ee_x = current_ee_x + offset_x
                        target_ee_y = current_ee_y + offset_y
                        target_ee_z = current_ee_z  # Keep Z
                        current_r = current_pos.get('r', 0)
                        

                        # Set current_end_effector correctly before move_linear
                        # Angled Pipette (mea2/mea-measure) is treated as pipette internally
                        if self.interface_manager.scara.current_end_effector != 'pipette':
                            logger.warning(f" [Angled Pipette - before spit] current_end_effector is {self.interface_manager.scara.current_end_effector}. Setting to pipette.")
                            self.interface_manager.scara.current_end_effector = 'pipette'
                            self.interface_manager.scara.current_with_tip = False  # Angled Pipette: with_tip=False
                            self.interface_manager.scara.current_tool_name = tool_name
                        

                        # Use same offset for IK as for current position calculation (consistency)
                        # Use same ik_solver
                        ik_solver_target = ik_solver  # Same ik_solver (same offset)
                        

                        # Determine right_handed (use same value as current position calculation)
                        right_handed_for_ik = right_handed  # Already calculated value
                        

                        # Run IK (keep current robot Z)
                        rv_target = ik_solver_target.inverse_kinematics_separated(
                            target_ee_x, target_ee_y, target_ee_z, right_handed=right_handed_for_ik
                        )
                        

                        logger.info(" [Angled Pipette - before spit] Inverse kinematics:")
                        logger.info(f" - Target end effector tip: x={target_ee_x:.2f}mm, y={target_ee_y:.2f}mm, z={target_ee_z:.2f}mm")
                        logger.info(f" - right_handed: {right_handed_for_ik}")
                        if rv_target:
                            logger.info(f" - Computed angles: angle1={rv_target[0]:.2f}°, angle2={rv_target[1]:.2f}°, z={rv_target[2]:.2f}mm")
                        

                        if rv_target is None:
                            logger.warning(" [Angled Pipette - before spit] Inverse kinematics failed, using fallback")
                            # Fallback: legacy method
                            result = self.interface_manager.scara.move_linear(
                                target_ee_x, target_ee_y, target_ee_z, current_r,
                                speed=10.0,
                                skip_gripper_rotation=True,
                                use_end_effector_coordinate=True,
                                with_tip=False,
                                tool_name=tool_name
                            )
                        else:
                            # Move to calculated angles (keep current Z)
                            target_angle1 = float(rv_target[0])
                            target_angle2 = float(rv_target[1])
                            # Key: keep current robot Z unchanged
                            target_robot_z = current_robot_z
                            

                            logger.info(f" [Angled Pipette - before spit] X,Y move (speed 5): x={offset_x:.3f}mm, y={offset_y:.3f}mm, Z kept={target_robot_z:.2f}mm")
                            result = self.interface_manager.scara.move_to_angle(
                                target_angle1, target_angle2, target_robot_z, current_r,
                                speed=10.0,
                                skip_gripper_rotation=True
                            )
                        if result.get('success', False):
                            logger.info(f" X,Y move done: x_offset={offset_x:.3f}mm, y_offset={offset_y:.3f}mm")
                        else:
                            logger.warning(f" X,Y move failed: {result.get('message', 'Unknown error')}")
                    else:
                        logger.warning(" [Angled Pipette - before spit] Cannot read position, skipping angle move.")
                except Exception as e:
                    logger.warning(f" [Angled Pipette - before spit] Error during angle move: {e}")
                    import traceback
                    traceback.print_exc()


            # Wait 0.5 seconds
            time.sleep(0.5)
            

            # For dispose_waste action: move X before dispensing
            command_type = parameters.get('type')
            is_dispose_waste = command_type == 'dispose' or parameters.get('action') == 'dispose_waste'
            

            if is_dispose_waste and amount == 0:
                # Move X by liq-trash radius
                try:
                    # Read current position
                    current_pos = self.interface_manager.scara.get_current_position()
                    if current_pos is None:
                        logger.warning(" Cannot read position, skipping X move")
                    else:
                        # Load liq-trash info from table_coordinates.json
                        import json
                        from pathlib import Path
                        

                        table_coords_path = Path("table_coordinates.json")
                        if table_coords_path.exists():
                            with open(table_coords_path, 'r', encoding='utf-8') as f:
                                table_coords = json.load(f)
                            

                            liq_trash_data = table_coords.get('tools', {}).get('liq-trash', {})
                            size = liq_trash_data.get('size', {})
                            

                            # Calculate radius
                            tool_radius = None
                            if 'dia' in size:
                                tool_radius = size.get('dia', 0) / 2.0
                            elif 'x' in size:
                                tool_radius = size.get('x', 0) / 2.0
                            else:
                                logger.warning(" liq-trash radius not found, using default 15mm")
                                tool_radius = 15.0
                            

                            # X move distance = radius + 2mm
                            x_offset = tool_radius + 3.0
                            logger.info(f" [Dispose] liq-trash radius: {tool_radius:.2f}mm, X move: {x_offset:.2f}mm (radius + 2mm)")
                            

                            # Move X by radius + 2mm
                            if abs(x_offset) > 0.01:  # Move only if difference > 0.01mm
                                # Use move_linear (specify robot coordinate system)
                                result = self.interface_manager.scara.move_linear(
                                    current_pos['x'] + x_offset,  # Robot coordinate system
                                    current_pos['y'],
                                    current_pos['z'],
                                    current_pos.get('r', 0),
                                    speed=20.0,
                                    skip_gripper_rotation=True,
                                    use_end_effector_coordinate=False  # Use robot coordinate system
                                )
                                if not result:
                                    logger.warning(" X move failed, continuing dispense")
                                else:
                                    # Wait for move completion
                                    if not self.interface_manager.scara.wait_for_movement_complete(timeout=self.movement_completion_timeout, action_commander=self.action_commander):
                                        logger.warning(" X-axis move completion wait timeout, continuing")
                                    logger.info(f" X move done: {x_offset:.2f}mm")
                        else:
                            logger.warning(" table_coordinates.json not found, skipping X move")
                except Exception as e:
                    logger.error(f" Error during X move: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    # Continue dispense even if error occurs
            

            # Execute liquid dispense command
            spit_result = self.interface_manager.daken.spit_liquid(amount)


            # Wait 0.5 seconds
            time.sleep(0.5)
            

            # If dispense succeeded and source_id provided: add liquid to tube (e.g. mix action)
            # (e.g. dispensing back to same source in mix action)
            if spit_result == "01":
                source_id = parameters.get('source_id')
                if self.tube_interface and source_id:
                    self._add_liquid_after_successful_dispense(source_id, amount)
            

            # For Angled Pipette (mea2/mea-measure) apply action:
            # Return offset in reverse direction after dispensing
            # Only for apply action (take action uses Pipette with tip)
            # Condition: pipette end effector, apply action, tool_name is mea2 or mea-measure
            action = parameters.get('action') or parameters.get('type')  # 'apply' or 'take'
            current_end_effector = self.interface_manager.scara.current_end_effector
            is_angled_pipette_mea = self._is_angled_pipette_mode('pipette', tool_name, current_end_effector)
            

            # Execute return move only for apply action
            if action == 'apply' and is_angled_pipette_mea:
                try:
                    # Read current angles after spit_liquid
                    # Get offset value from settings
                    if self.config_manager:
                        _offset = self.config_manager.get("offset_distance", "angled_pipette_offset") or 2.0
                    else:
                        _offset = 2.0  # Default value
                    

                    # Brief wait for position to stabilize after pre-spit move
                    # Re-read position after short delay
                    time.sleep(0.2)  # Wait 200ms
                    

                    # Read actual encoder Z for better accuracy
                    self.interface_manager.scara.robot.get_encoder_coor()
                    actual_robot_z = self.interface_manager.scara.robot.encoder_z
                    

                    current_pos = self.interface_manager.scara.get_current_position()
                    if current_pos:
                        current_angle1 = current_pos.get('angle1', 0)
                        current_angle2 = current_pos.get('angle2', 0)
                        current_robot_z_from_pos = current_pos.get('z', 0)
                        

                        # Prefer actual encoder Z
                        # Use encoder Z if it differs from get_current_position
                        if abs(current_robot_z_from_pos - actual_robot_z) > 0.5:
                            logger.warning(f" [Angled Pipette - return] get_current_position() Z ({current_robot_z_from_pos:.2f}mm) != encoder Z ({actual_robot_z:.2f}mm). Using encoder.")
                            current_robot_z = actual_robot_z
                        else:
                            current_robot_z = current_robot_z_from_pos
                        

                        logger.debug(f" [Angled Pipette - return] Current robot Z: {current_robot_z:.2f}mm (encoder: {actual_robot_z:.2f}mm, get_current_position: {current_robot_z_from_pos:.2f}mm)")
                        

                        # Determine coordinate mode per tool
                        # Angled Pipette mea2/mea-measure handling
                        effective_end_effector = 'pipette'  # mea2, mea-measure always treated as pipette
                        right_handed = self._determine_right_handed(effective_end_effector, tool_name)
                        if right_handed is None:
                            # mea-measure is left-handed
                            right_handed = False
                        

                        # Calculate end effector direction angle
                        # Right-handed: angle1 + angle2
                        # Left-handed: angle1 + angle2 - 90 degrees (bent 90 degrees inward)
                        if right_handed:
                            # Right-handed: angle1 + angle2
                            end_effector_angle_deg = current_angle1 + current_angle2
                        else:
                            # Left-handed: angle1 + angle2 - 90 degrees
                            end_effector_angle_deg = current_angle1 + current_angle2 - 90.0
                        

                        end_effector_angle_rad = math.radians(end_effector_angle_deg)
                        

                        # Calculate X, Y offset for return (reverse direction, negative values)
                        # Reverse direction uses negative values
                        # X axis: -cos, Y axis: -sin (SCARA robot coordinate system)
                        offset_x = -_offset * math.cos(end_effector_angle_rad)
                        offset_y = -_offset * math.sin(end_effector_angle_rad)
                        

                        logger.debug(f" [Angled Pipette - return] Current angles: angle1={current_angle1:.2f}°, angle2={current_angle2:.2f}°")
                        logger.debug(f" [Angled Pipette - return] Coordinate mode: {'right-handed' if right_handed else 'left-handed'}")
                        logger.debug(f" [Angled Pipette - return] End effector direction: {end_effector_angle_deg:.2f}° (base: {current_angle1 + current_angle2:.2f}° {'+ 0' if right_handed else '- 90'}°)")
                        logger.debug(f" [Angled Pipette - return] {_offset}mm opposite move: x_offset={offset_x:.3f}mm, y_offset={offset_y:.3f}mm")
                        

                        # Get Z rise amount from settings
                        if self.config_manager:
                            z_offset = self.config_manager.get("offset_distance", "angled_pipette_post_dispense_z_offset") or 3.0
                        else:
                            z_offset = 3.0  # Default value
                        

                        # Use correct offset for current end effector tip calculation
                        # For apply action: always use with_tip=False for pipette_with_tip_15degree offset
                        from ikine2 import inv_kinematics
                        ee_offset = self.interface_manager.scara.get_end_effector_offset(
                            effective_end_effector,
                            False,  # Explicitly set False to use pipette_with_tip_15degree
                            tool_name
                        )
                        ik_solver = inv_kinematics(dx=ee_offset['x'], dy=ee_offset['y'], dz=ee_offset['z'])
                        # Use actual robot Z value
                        current_ee_pos = ik_solver.forward_kinematics(current_angle1, current_angle2, current_robot_z)
                        current_ee_x, current_ee_y, current_ee_z = current_ee_pos
                        

                        logger.debug(" [Angled Pipette - return] Current end effector tip position:")
                        logger.debug(f" - Robot Z: {current_robot_z:.2f}mm")
                        logger.debug(f" - End effector offset (with_tip=False): {ee_offset}")
                        logger.debug(f" - Computed end effector tip: x={current_ee_x:.2f}mm, y={current_ee_y:.2f}mm, z={current_ee_z:.2f}mm")
                        

                        # Target end effector tip position (return X,Y and rise Z simultaneously)
                        target_ee_x = current_ee_x + offset_x
                        target_ee_y = current_ee_y + offset_y
                        target_ee_z = current_ee_z + z_offset  # Rise Z simultaneously
                        current_r = current_pos.get('r', 0)
                        

                        logger.debug(" [Angled Pipette - return] Target end effector tip:")
                        logger.debug(f" - Target: x={target_ee_x:.2f}mm, y={target_ee_y:.2f}mm, z={target_ee_z:.2f}mm")
                        logger.debug(f" - right_handed: {right_handed}")
                        

                        # Set current_end_effector correctly before move_linear
                        # Angled Pipette (mea2/mea-measure) is treated as pipette internally
                        if self.interface_manager.scara.current_end_effector != 'pipette':
                            logger.warning(f" [Angled Pipette - return] current_end_effector is {self.interface_manager.scara.current_end_effector}. Setting to pipette.")
                            self.interface_manager.scara.current_end_effector = 'pipette'
                            self.interface_manager.scara.current_with_tip = False  # Angled Pipette: with_tip=False
                            self.interface_manager.scara.current_tool_name = tool_name
                        

                        # Move Z, X, Y simultaneously (use move_linear in end effector coordinate system)
                        logger.debug(f" [Angled Pipette - return] Z,X,Y move (speed 5): z={z_offset}mm, x={offset_x:.3f}mm, y={offset_y:.3f}mm")
                        move_result = self.interface_manager.scara.move_linear(
                            target_ee_x, target_ee_y, target_ee_z, current_r,
                            speed=10.0,
                            skip_gripper_rotation=True,
                            use_end_effector_coordinate=True,
                            with_tip=False,  # Angled Pipette: always with_tip=False
                            tool_name=tool_name
                        )
                        if move_result.get('success', False):
                            logger.debug(f" Z,X,Y move done: z={z_offset}mm, x_offset={offset_x:.3f}mm, y_offset={offset_y:.3f}mm")
                        else:
                            logger.warning(f" Z,X,Y move failed: {move_result.get('message', 'Unknown error')}")
                    else:
                        logger.warning(" [Angled Pipette - return] Cannot read position, skipping angle return.")
                except Exception as e:
                    logger.warning(f" [Angled Pipette - return] Error during angle return: {e}")
                    import traceback
                    traceback.print_exc()


            # wait 200 msec
            time.sleep(self.liquid_spit_post_wait)
            

            # For dispose_waste action: return X after dispensing
            if is_dispose_waste and amount == 0:
                try:
                    # Load liq-trash info from table_coordinates.json
                    import json
                    from pathlib import Path
                    

                    table_coords_path = Path("table_coordinates.json")
                    if table_coords_path.exists():
                        with open(table_coords_path, 'r', encoding='utf-8') as f:
                            table_coords = json.load(f)
                        

                        liq_trash_data = table_coords.get('tools', {}).get('liq-trash', {})
                        size = liq_trash_data.get('size', {})
                        

                        # Calculate radius
                        tool_radius = None
                        if 'dia' in size:
                            tool_radius = size.get('dia', 0) / 2.0
                        elif 'x' in size:
                            tool_radius = size.get('x', 0) / 2.0
                        else:
                            tool_radius = 15.0  # Default value
                        

                        # X return distance = radius + 2mm (same as pre-dispense move)
                        x_offset_return = tool_radius + 2.0
                        

                        # Read current position after dispense
                        current_pos_after_spit = self.interface_manager.scara.get_current_position()
                        if current_pos_after_spit and abs(x_offset_return) > 0.01:
                            logger.info(f" [Dispose] X return: -{x_offset_return:.2f}mm (return to liq-trash center, radius + 2mm)")
                            # Move in reverse direction (negative offset)
                            result = self.interface_manager.scara.move_linear(
                                current_pos_after_spit['x'] - x_offset_return,  # Reverse (robot coordinate)
                                current_pos_after_spit['y'],
                                current_pos_after_spit['z'],
                                current_pos_after_spit.get('r', 0),
                                speed=20.0,
                                skip_gripper_rotation=True,
                                use_end_effector_coordinate=False  # Use robot coordinate system
                            )
                            if not result:
                                logger.warning(" X return move failed, continuing")
                            else:
                                # Wait for move completion
                                if not self.interface_manager.scara.wait_for_movement_complete(timeout=self.movement_completion_timeout, action_commander=self.action_commander):
                                    logger.warning(" X return move completion wait timeout, continuing")
                                logger.info(" X return done (returned to liq-trash center)")
                                

                                # Last step of dispose action: aspirate 30uL
                                # Skip if all remaining liquid was already aspirated in last take action
                                should_skip_30ul = False
                                if self.last_take_source_id and self.tube_interface:
                                    try:
                                        # Check current volume of last take action source
                                        manager = self.tube_interface.factory.get_tube_manager_by_table_name(self.last_take_source_id)
                                        if manager:
                                            current_volume = manager.current_volume_ul
                                            if current_volume <= 0:
                                                should_skip_30ul = True
                                                logger.info(f" dispose: Last take ({self.last_take_source_id}) aspirated remainder, skipping 30μL dispense.")
                                    except Exception as e:
                                        logger.warning(f" dispose: Error checking 30μL dispense: {e}. Continuing.")
                                

                                if not should_skip_30ul:
                                    logger.info(" dispose last step: aspirate 30μL")
                                    aspirate_result = self.interface_manager.daken.aspirate_liquid(30)
                                    if aspirate_result == "01":
                                        logger.info(" Aspirate 30μL success")
                                    else:
                                        logger.warning(f" Aspirate 30μL failed (result: {aspirate_result})")
                                else:
                                    logger.info(" dispose: Skipping 30μL dispense (remainder aspirated).")
                        else:
                            logger.warning(" Cannot read position after dispense, skipping X return")
                except Exception as e:
                    logger.error(f" Error during X return: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    # Continue even if error occurs
            

            if spit_result == "01":
                logger.info(" Liquid dispense success")
                return True
            else:
                logger.warning(f" Liquid dispense failed (result: {spit_result})")
                return False


        except Exception as e:
            logger.error(f" DAKEN liquid dispense error: {e}")
            return False
    

    def _execute_daken_initialize(self, parameters: Dict[str, Any]) -> bool:
        """Execute DAKEN initialize command."""
        if not self.interface_manager.connected_interfaces['daken']:
            logger.error(" DAKEN interface not connected")
            return False
        

        try:
            logger.info(f" {tr('message.daken.initializing')}")
            

            # Execute DAKEN initialization command
            result = self.interface_manager.daken.initialize()
            

            if result == "OK":
                logger.info(f" {tr('message.daken.initialized')}")
                return True
            elif result == "Error":
                logger.error(" DAKEN initialization error")
                return False
            elif result == "Timeout":
                logger.error(" DAKEN initialization timeout")
                return False
            else:
                logger.warning(f" Unknown init result: {result}")
                return False
            

        except Exception as e:
            logger.error(f" DAKEN initialization error: {e}")
            return False
    

    def _execute_daken_aspirate_first_air(self, parameters: Dict[str, Any]) -> bool:
        """Execute DAKEN aspirate_first_air command."""
        if not self.interface_manager.connected_interfaces['daken']:
            logger.error(" DAKEN interface not connected")
            return False
        

        try:
            logger.info(" DAKEN first air aspiration...")
            

            # Execute DAKEN first air aspiration command
            result = self.interface_manager.daken.aspirate_first_air()
            

            if result == "01":
                logger.info(" First air aspiration success")
                return True
            else:
                logger.warning(f" First air aspiration result: {result}")
                return False
            

        except Exception as e:
            logger.error(f" DAKEN first air aspiration error: {e}")
            return False
    

    def _execute_daken_reject_tip(self, parameters: Dict[str, Any]) -> bool:
        """Execute DAKEN tip reject command."""
        if not self.interface_manager.connected_interfaces['daken']:
            logger.error(" DAKEN interface not connected")
            return False
        

        try:
            logger.info(" DAKEN tip eject...")
            

            # Execute DAKEN tip reject command
            result = self.interface_manager.daken.reject_tip()
            

            if result == "OK":
                logger.info(" Tip eject success")
                return True
            else:
                logger.warning(f" Tip eject result: {result}")
                return False
            

        except Exception as e:
            logger.error(f" DAKEN tip eject error: {e}")
            return False
    

    def _execute_servo_move_angle(self, parameters: Dict[str, Any]) -> bool:
        """Execute Servo move_to_angle command."""
        if not self.interface_manager.connected_interfaces['servo']:
            logger.error(" Servo interface not connected")
            return False
        

        try:
            angle = parameters.get('angle', 0)
            wait_time = parameters.get('wait_time', 1.0)
            

            logger.info(f" Servo angle move: {angle}°")
            

            # Execute Servo angle move command
            result = self.interface_manager.servo.move_to_angle(angle, wait_time)
            

            return result
            

        except Exception as e:
            logger.error(f" Servo angle move error: {e}")
            return False
    

    def _execute_gripper_open(self, parameters: Dict[str, Any]) -> bool:
        """Execute gripper open command."""
        # Gripper is included in SCARA; check SCARA connection
        if not self.interface_manager.connected_interfaces['scara']:
            logger.error(" SCARA interface is not connected (gripper unavailable)")
            return False
        

        # Skip if current end effector is not gripper
        if self.interface_manager.scara.current_end_effector != 'gripper':
            logger.warning(f" Skipping gripper command: current_end_effector={self.interface_manager.scara.current_end_effector} (not gripper)")
            return True  # Not an error; command is skipped
        

        # Get gripper object from SCARA
        gripper = self.interface_manager.scara.get_gripper()
        if not gripper:
            logger.error(" Cannot get gripper object")
            return False
        

        # Auto-initialize gripper if not initialized
        if not gripper.initialized:
            logger.info(" Attempting gripper auto initialization...")
            if not gripper.initialize():
                logger.error(" Gripper initialization failed")
                return False
            logger.info(" Gripper auto initialization completed")
        

        try:
            # Extract distance and speed from parameters
            distance = parameters.get('distance', 10.0)  # Default: maximum distance
            speed = parameters.get('speed', 50)  # Default: medium speed
            

            logger.info(f" Gripper open (distance: {distance}mm, speed: {speed})")
            

            # Check action and tool_name parameters (save place context if needed)
            action = parameters.get('action')
            tool_name = parameters.get('tool_name')
            if action == 'place' and tool_name and 'mea' in tool_name.lower():
                location = tool_name.lower()
                self.current_place_context = {
                    'action': 'place',
                    'location': location,
                    'tool_name': tool_name
                }
                logger.info(f" [MEA Stack] Place context saved: {location} (quantity will increase on gripper open)")
            

            # Execute gripper open command
            # Note: gripper angle adjustment is done at the topmost position of the destination
            # (handled by move_end_effector or move_to_top)
            result = gripper.open(distance, speed)
            

            if result:
                logger.info(" Gripper open completed")
                

                # For place action: run position correction (mea2 and mea-measure only)
                if action == 'place' and tool_name:
                    location = tool_name.lower()
                    # Apply only for mea2 and mea-measure locations
                    if location in ['mea2', 'mea-measure']:
                        logger.info(f" Place action: position correction test ({location})...")
                        try:
                            # 0. Move Z from place offset to pick offset
                            logger.info(" Z move to MEA pick offset (place offset → pick offset)...")
                            try:
                                # Check and create height_calculator
                                if hasattr(self, 'stack_manager') and self.stack_manager:
                                    if not hasattr(self, 'height_calculator') or self.height_calculator is None:
                                        try:
                                            import sys
                                            import os
                                            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                                            if project_root not in sys.path:
                                                sys.path.insert(0, project_root)
                                            from utils.mea_height_calculator import MEAHeightCalculator
                                            self.height_calculator = MEAHeightCalculator(self.stack_manager)
                                            logger.info(" MEAHeightCalculator dynamically created")
                                        except Exception as e:
                                            logger.warning(f" MEAHeightCalculator creation failed: {e}")
                                            self.height_calculator = None
                                

                                if self.height_calculator:
                                    # Select place_offset based on location
                                    if location == "mea2":
                                        place_offset = self.height_calculator.gripper_place_offset_mea2
                                    elif location == "mea-measure":
                                        place_offset = self.height_calculator.gripper_place_offset_mea_measure
                                    else:
                                        # mea1, mea3 etc. are treated same as mea2
                                        place_offset = self.height_calculator.gripper_place_offset_mea2
                                    

                                    pick_offset = self.height_calculator.gripper_pick_offset
                                    

                                    # Calculate difference between pick and place offsets
                                    # Place offset position: tool top - place_offset
                                    # Pick offset position: tool top - pick_offset
                                    # Difference = (tool_top - pick_offset) - (tool_top - place_offset) = place_offset - pick_offset
                                    # place_offset - pick_offset is negative (move downward)
                                    z_offset = place_offset - pick_offset
                                    

                                    logger.info(f" - Pick offset: {pick_offset:.2f}mm")
                                    logger.info(f" - Place offset ({location}): {place_offset:.2f}mm")
                                    logger.info(f" - Z move offset: {z_offset:.2f}mm (place → pick offset, downward)")
                                    

                                    # Move Z (move_offset operates in end effector tip coordinate system)
                                    result = self.interface_manager.scara.move_offset('z', z_offset, speed=10.0, skip_gripper_rotation=True, tool_name=location)
                                    if result:
                                        logger.info(" Z move done (moved to pick offset)")
                                    else:
                                        logger.warning(" Z move failed")
                                else:
                                    logger.warning(" height_calculator unavailable, skipping Z move")
                            except Exception as e:
                                logger.warning(f" Z move error: {e}")
                                import traceback
                                traceback.print_exc()
                            

                            time.sleep(0.5)
                            

                            # 1. Adjust gripper to 4mm
                            logger.info(" Adjusting gripper to 4mm...")
                            if not gripper.set_clamping_distance(4.0):
                                logger.warning(" Gripper 4mm adjustment failed")
                            else:
                                logger.info(" Gripper 4mm adjustment completed")
                            time.sleep(1.0)
                            

                            # 2. Y-axis alignment test (read align_distance from settings)
                            logger.info(" Y-axis move test starting...")
                            align_distance = self.align_distance  # Value read from settings
                            try:
                                # Move Y +2.5mm
                                logger.info(f" Y +{align_distance}mm move...")
                                result = self.interface_manager.scara.move_offset('y', align_distance, speed=50.0, skip_gripper_rotation=True)
                                if result:
                                    logger.info(f" Y +{align_distance}mm move done")
                                else:
                                    logger.warning(f" Y +{align_distance}mm move failed")
                                

                                # Move Y -5mm
                                logger.info(f" Y -{align_distance * 2}mm move...")
                                result = self.interface_manager.scara.move_offset('y', -align_distance * 2, speed=50.0, skip_gripper_rotation=True)
                                if result:
                                    logger.info(f" Y -{align_distance * 2}mm move done")
                                else:
                                    logger.warning(f" Y -{align_distance * 2}mm move failed")
                                

                                # Move Y +5mm
                                logger.info(f" Y +{align_distance * 2}mm move...")
                                result = self.interface_manager.scara.move_offset('y', align_distance * 2, speed=50.0, skip_gripper_rotation=True)
                                if result:
                                    logger.info(f" Y +{align_distance * 2}mm move done")
                                else:
                                    logger.warning(f" Y +{align_distance * 2}mm move failed")
                                

                                # Move Y -5mm
                                logger.info(f" Y -{align_distance * 2}mm move...")
                                result = self.interface_manager.scara.move_offset('y', -align_distance * 2, speed=50.0, skip_gripper_rotation=True)
                                if result:
                                    logger.info(f" Y -{align_distance * 2}mm move done")
                                else:
                                    logger.warning(f" Y -{align_distance * 2}mm move failed")
                                

                                # Move Y +2.5mm (return to origin)
                                logger.info(f" Y +{align_distance}mm move (return to origin)...")
                                result = self.interface_manager.scara.move_offset('y', align_distance, speed=5.0, skip_gripper_rotation=True)
                                if result:
                                    logger.info(f" Y +{align_distance}mm move done (return to origin)")
                                else:
                                    logger.warning(f" Y +{align_distance}mm move failed")
                            except Exception as e:
                                logger.warning(f" Y-axis move test error: {e}")
                            

                            # 3. Adjust gripper to 1mm
                            logger.info(" Adjusting gripper to 1mm...")
                            if not gripper.set_clamping_distance(1.0):
                                logger.warning(" Gripper 1mm adjustment failed")
                            else:
                                logger.info(" Gripper 1mm adjustment completed")
                            time.sleep(1.0)
                            

                            # 4. Adjust gripper to 10mm
                            logger.info(" Adjusting gripper to 10mm...")
                            if not gripper.set_clamping_distance(10.0):
                                logger.warning(" Gripper 10mm adjustment failed")
                            else:
                                logger.info(" Gripper 10mm adjustment done")
                            time.sleep(1.0)
                        except Exception as e:
                            logger.warning(f" Position correction test error: {e}")
                

                # For place action: increase MEA Stack count (at gripper open)
                if self.current_place_context and self.stack_manager:
                    location = self.current_place_context.get('location')
                    if location:
                        try:
                            if self.stack_manager.add_tool(location):
                                count = self.stack_manager.get_stack_count(location)
                                logger.info(f" [MEA Stack] Place done: tool added at {location} (count: {count})")
                                self._notify_gui_update(location)
                            else:
                                logger.warning(f" [MEA Stack] Place failed: cannot add tool at {location} (max count reached)")
                        except Exception as e:
                            logger.warning(f" [MEA Stack] Place quantity error: {e}")
                        finally:
                            # Reset context
                            self.current_place_context = None
            else:
                logger.error(" Gripper open failed")
            

            return result
            

        except Exception as e:
            logger.error(f" Gripper open error: {e}")
            return False
    

    def _execute_gripper_close(self, parameters: Dict[str, Any]) -> bool:
        """Execute gripper close command."""
        # Gripper is included in SCARA; check SCARA connection
        if not self.interface_manager.connected_interfaces['scara']:
            logger.error(" SCARA interface is not connected (gripper unavailable)")
            return False
        

        # Skip if current end effector is not gripper
        if self.interface_manager.scara.current_end_effector != 'gripper':
            logger.warning(f" Skipping gripper command: current_end_effector={self.interface_manager.scara.current_end_effector} (not gripper)")
            return True  # Not an error; command is skipped
        

        # Get gripper object from SCARA
        gripper = self.interface_manager.scara.get_gripper()
        if not gripper:
            logger.error(" Cannot get gripper object")
            return False
        

        # Auto-initialize gripper if not initialized
        if not gripper.initialized:
            logger.info(" Attempting gripper auto initialization...")
            if not gripper.initialize():
                logger.error(" Gripper initialization failed")
                return False
            logger.info(" Gripper auto initialization completed")
        

        try:
            # Extract distance and speed from parameters
            distance = parameters.get('distance', 0.0)  # Default: minimum distance
            speed = parameters.get('speed', 50)  # Default: medium speed
            

            logger.info(f" Gripper close (distance: {distance}mm, speed: {speed})")
            

            # Check action and tool_name parameters (save pick context if needed)
            action = parameters.get('action')
            tool_name = parameters.get('tool_name')
            if action == 'pick' and tool_name and 'mea' in tool_name.lower():
                location = tool_name.lower()
                self.current_pick_context = {
                    'action': 'pick',
                    'location': location,
                    'tool_name': tool_name
                }
                logger.info(f" [MEA Stack] Pick context saved: {location} (quantity will decrease on gripper close)")
            

            # Execute gripper close command
            result = gripper.close(distance, speed)
            

            if result:
                logger.info(" Gripper close completed")
                

                # For pick action: decrease MEA Stack count (at gripper close)
                if self.current_pick_context and self.stack_manager:
                    location = self.current_pick_context.get('location')
                    if location:
                        try:
                            if self.stack_manager.remove_tool(location):
                                count = self.stack_manager.get_stack_count(location)
                                logger.info(f" [MEA Stack] Pick done: tool removed from {location} (count: {count})")
                                self._notify_gui_update(location)
                            else:
                                logger.warning(f" [MEA Stack] Pick failed: cannot remove tool from {location} (insufficient or over max count)")
                        except Exception as e:
                            logger.warning(f" [MEA Stack] Pick quantity error: {e}")
                        finally:
                            # Reset context
                            self.current_pick_context = None
            else:
                logger.error(" Gripper close failed")
            

            return result
            

        except Exception as e:
            logger.error(f" Gripper close error: {e}")
            return False
    

    def _execute_measurement_start(self, parameters: Dict[str, Any]) -> bool:
        """Execute start_measurement command (realtime graph window shown automatically)."""
        if not self.interface_manager.connected_interfaces['measurement']:
            logger.error(" Measurement interface not connected")
            return False
        

        try:
            measurement_type = parameters.get('measurement_type', 'eis')
            sample_position = parameters.get('sample_position', 0)
            measurement_params = parameters.get('measurement_params', {})
            

            logger.info(f" Measurement start: {measurement_type.upper()}, position: {sample_position}")
            

            # Create and display realtime graph window
            realtime_window = None
            realtime_plotter = None
            

            try:
                from measurement_report_viewer import RealtimeMeasurementWindow
                from PySide6.QtWidgets import QApplication
                from PySide6.QtCore import QMetaObject, Qt, QThread
                

                # Find main window (use as parent)
                app = QApplication.instance()
                parent_window = None
                if app:
                    for widget in app.allWidgets():
                        if hasattr(widget, 'windowTitle') and 'Protocol' in str(widget.windowTitle()):
                            parent_window = widget
                            break
                

                # Create realtime graph window on main thread
                logger.info(f" Creating realtime graph window: {measurement_type}")
                

                # Check current thread
                current_thread = QThread.currentThread()
                main_thread = app.thread() if app else None
                

                if app and current_thread != main_thread:
                    # Running in worker thread: create window on main thread via Signal
                    logger.info(" Running in another thread. Creating window on main thread via Signal")
                    

                    # Variable to store result
                    result_holder = [None, None] # [window, plotter]
                    import threading
                    event = threading.Event()
                    

                    # Create window on main thread using ProtocolMakerWindow Signal
                    if parent_window and hasattr(parent_window, 'create_realtime_window_requested'):
                        # Emit Signal (runs on main thread)
                        parent_window.create_realtime_window_requested.emit(measurement_type, result_holder)
                        

                        # Wait until main thread processes it (max 3 seconds)
                        # Wait for Signal to be processed
                        import time
                        start_time = time.time()
                        while time.time() - start_time < 3.0:
                            if result_holder[0] is not None or result_holder[1] is not None:
                                break
                            time.sleep(0.1)
                            # Allow event loop to process
                            if app:
                                app.processEvents()
                        

                        realtime_window = result_holder[0]
                        realtime_plotter = result_holder[1]
                        if realtime_window:
                            logger.info(f" Realtime graph window created: {measurement_type}")
                        else:
                            logger.warning(" Realtime graph window creation failed")
                    else:
                        # Create directly if no Signal available (not recommended)
                        logger.warning(" ProtocolMakerWindow not found. Creating directly")
                        realtime_window = RealtimeMeasurementWindow(measurement_type, parent_window)
                        realtime_window.show()
                        realtime_window.raise_()
                        realtime_window.activateWindow()
                        realtime_window.update_status(f"{measurement_type.upper()} measurement starting...")
                        realtime_plotter = realtime_window.get_realtime_plotter()
                else:
                    # Running on main thread: create directly
                    realtime_window = RealtimeMeasurementWindow(measurement_type, parent_window)
                    realtime_window.show()
                    realtime_window.raise_()
                    realtime_window.activateWindow()
                    realtime_window.update_status(f"{measurement_type.upper()} measurement starting...")
                    realtime_plotter = realtime_window.get_realtime_plotter()
                    if realtime_plotter:
                        logger.info(f" Realtime graph window created: {measurement_type}")
                    else:
                        logger.warning(" Cannot get realtime plotter")
                

            except Exception as e:
                logger.warning(f"Realtime graph window creation failed: {e}")
                import traceback
                logger.warning(traceback.format_exc())
                # Measurement continues even without realtime graph window
                realtime_window = None
                realtime_plotter = None
            

            # Start realtime measurement
            if realtime_plotter:
                result = self.interface_manager.measurement.start_measurement_realtime(
                    measurement_type=measurement_type,
                    sample_position=sample_position,
                    measurement_params=measurement_params,
                    realtime_plotter=realtime_plotter
                )
            else:
                # Fall back to legacy method if no realtime plotter
                result = self.interface_manager.measurement.start_measurement(
                    measurement_type=measurement_type,
                    sample_position=sample_position,
                    measurement_params=measurement_params
                )
            

            # Update status (check if window is still open)
            if realtime_window:
                try:
                    # Check if window is still valid
                    if hasattr(realtime_window, '_is_closing') and realtime_window._is_closing:
                        # Skip update if window is closing
                        logger.info(" Realtime graph window closing, skipping state update")
                    elif hasattr(realtime_window, 'isVisible') and not realtime_window.isVisible():
                        # Skip update if window is already closed
                        logger.info(" Realtime graph window already closed, skipping state update")
                    else:
                        if result:
                            # Get measurement result file path
                            measurement_system = self.interface_manager.measurement
                            if hasattr(measurement_system, 'measurement_results') and measurement_system.measurement_results:
                                last_result = measurement_system.measurement_results[-1]
                                if 'filepath' in last_result:
                                    filepath = last_result['filepath']
                                    filename = os.path.basename(filepath) if filepath else "Unknown"
                                    realtime_window.update_status(f" {measurement_type.upper()} measurement completed\n File: {filename}")
                                    logger.info(f" {measurement_type.upper()} measurement completed - file: {filepath}")
                                else:
                                    realtime_window.update_status(f" {measurement_type.upper()} measurement completed")
                                    logger.info(f" {measurement_type.upper()} measurement completed")
                            else:
                                realtime_window.update_status(f" {measurement_type.upper()} measurement completed")
                                logger.info(f" {measurement_type.upper()} measurement completed")
                        else:
                            realtime_window.update_status(f" {measurement_type.upper()} measurement failed")
                            logger.error(f" {measurement_type.upper()} measurement failed")
                except RuntimeError:
                    # Widget may have already been deleted
                    logger.warning(" Realtime graph window already destroyed")
                except Exception as e:
                    # Log other exceptions and continue
                    logger.warning(f" Realtime graph window state update failed: {e}")
            

            if result:
                logger.info(f" {measurement_type.upper()} measurement completed")
            else:
                logger.error(f" {measurement_type.upper()} measurement failed")
            

            return result
            

        except Exception as e:
            logger.error(f" Measurement execution error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    

    def _execute_tip_equip_with_retry(self, parameters: Dict[str, Any]) -> bool:
        """Tip attach (with retry)."""
        if not self.interface_manager.connected_interfaces['scara']:
            logger.error(" SCARA interface is not connected")
            return False
        

        if not self.interface_manager.connected_interfaces['daken']:
            logger.error(" DAKEN interface not connected")
            return False
        

        max_retries = parameters.get('max_retries', self.tip_equip_max_retries)
        retry_delay = parameters.get('retry_delay', self.retry_delay)
        z_offset = parameters.get('z_offset', self.tip_equip_z_offset)  # Default from settings
        

        for attempt in range(max_retries):
            try:
                logger.info(f" Tip attach attempt {attempt + 1}/{max_retries}")
                

                # Step 1: Move Z down (attempt tip attach)
                logger.info(f" Z -{z_offset}mm move (tip attach attempt)")
                scara_result = self.interface_manager.scara.move_offset('z', -z_offset, speed=self.tip_equip_z_axis_speed, skip_gripper_rotation=True)
                if not scara_result:
                    logger.error(f" Z -{z_offset}mm move failed")
                    continue
                

                time.sleep(self.tip_equip_wait_time)  # Wait for tip attach
                

                # Step 2: Move Z back up (tip attach complete)
                logger.info(f" Z +{z_offset}mm move (tip attach done)")
                scara_result = self.interface_manager.scara.move_offset('z', z_offset, speed=self.tip_equip_z_axis_speed, skip_gripper_rotation=True)
                if not scara_result:
                    logger.error(f" Z +{z_offset}mm move failed")
                    continue
                

                time.sleep(self.tip_equip_wait_time)  # Wait for tip check
                

                # Step 3: Check tip
                logger.info(" Checking tip attach...")
                tip_status = self.interface_manager.daken.check_tip()
                

                if tip_status == "01":
                    logger.info(" Tip attach success")
                    # Last step of equip action: aspirate 30uL
                    logger.info(" equip action last step: aspirate 30μL")
                    aspirate_result = self.interface_manager.daken.aspirate_liquid(30)
                    if aspirate_result == "01":
                        logger.info(" Aspirate 30μL success")
                    else:
                        logger.warning(f" Aspirate 30μL failed (result: {aspirate_result})")
                    return True
                elif tip_status == "02":
                    #logger.warning(f"No tip detected (attempt {attempt + 1}/{max_retries})")
                    logger.error(f" Tip check error: {tip_status}")
                    return False
                    # if attempt < max_retries - 1:
                    #     # Step 4: Move Z for retry (+7mm, -7mm)
                    #     logger.info("Z axis move for retry...")
                    # self.interface_manager.scara.move_offset('z', z_offset, speed=10, skip_gripper_rotation=True)
                    # time.sleep(0.3)
                    # self.interface_manager.scara.move_offset('z', -z_offset, speed=10, skip_gripper_rotation=True)
                    # time.sleep(0.3)
                    # self.interface_manager.scara.move_offset('z', z_offset, speed=10, skip_gripper_rotation=True)
                        

                    # logger.info(f" Retrying in {retry_delay}s...")
                    # time.sleep(retry_delay)
                    # continue
                    # else:
                    #     logger.error("Max retries exceeded: no tip")
                    # return False
                elif tip_status == "03":
                    logger.error(f" Tip check error (attempt {attempt + 1}/{max_retries})")
                    if attempt < max_retries - 1:
                        logger.info(f" Retrying in {retry_delay}s...")
                        time.sleep(retry_delay)
                        continue
                    else:
                        logger.error(" Max retries exceeded: tip check error")
                        return False
                else:
                    logger.warning(f" Unknown tip status: {tip_status}")
                    return False
                    

            except Exception as e:
                logger.error(f" Tip attach error (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    logger.info(f" Retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                    continue
                else:
                    return False
        

        return False
    

    def _execute_jig_open(self, parameters: Dict[str, Any]) -> bool:
        """Execute JIG open command (move to HOME position)."""
        if not self.interface_manager.connected_interfaces['jig']:
            logger.error(" JIG interface not connected")
            return False
        

        try:
            wait_for_completion = parameters.get('wait_for_completion', True)
            

            logger.info(" Opening JIG... (moving to HOME position)")
            

            # Execute JIG open
            result = self.interface_manager.jig.open(wait_for_completion)
            

            if result:
                logger.info(" JIG open completed")
                # Delay for stabilization after movement
                logger.info(" Waiting for JIG stabilization... (5s)")
                time.sleep(5)
            else:
                logger.error(" JIG open failed")
            

            return result
            

        except Exception as e:
            logger.error(f" JIG open error: {e}")
            return False
    

    def _execute_jig_close(self, parameters: Dict[str, Any]) -> bool:
        """Execute JIG close command (move to END position)."""
        if not self.interface_manager.connected_interfaces['jig']:
            logger.error(" JIG interface not connected")
            return False
        

        try:
            wait_for_completion = parameters.get('wait_for_completion', True)
            

            logger.info(" Closing JIG... (moving to END position)")
            

            # Execute JIG close
            result = self.interface_manager.jig.close(wait_for_completion)
            

            if result:
                logger.info(" JIG close completed")
                # Delay for stabilization after movement
                logger.info(" Waiting for JIG stabilization... (5s)")
                time.sleep(5)
            else:
                logger.error(" JIG close failed")
            

            return result
            

        except Exception as e:
            logger.error(f" JIG close error: {e}")
            return False


    def _execute_time_sleep(self, parameters: Dict[str, Any]) -> bool:
        """Execute time sleep command."""
        try:
            seconds = parameters.get('seconds', 0)
            

            if seconds <= 0:
                logger.info(" Wait time is 0 or less. Skipping.")
                return True
            

            logger.info(f" Waiting {seconds} seconds...")
            time.sleep(seconds)
            logger.info(f" Wait {seconds} seconds completed")
            

            return True
            

        except Exception as e:
            logger.error(f" Error during wait: {e}")
            return False
    

    def _handle_tube_operations_with_source_id(self, source_id, amount):
        """Handle Tube Interface operations for the given source_id."""
        try:
            if not self.tube_interface or not source_id:
                return
            

            logger.info(f" Source ID: {source_id}")
            

            # Run surface detection and correction
            self._perform_surface_detection_and_correction(source_id)
            

        except Exception as e:
            logger.error(f" Tube operation error: {e}")
    

    

    def _get_table_center_z(self):
        import os
        import yaml
        """Read the table center Z value from table.yaml."""
        table_yaml_path = os.path.join("config", "table.yaml")
        with open(table_yaml_path, 'r') as f:
            table_config = yaml.safe_load(f)
            # table.yaml structure: settings -> table -> table -> center -> z
            table_center_z = table_config.get('settings', {}).get('table', {}).get('table', {}).get('center', {}).get('z', 0)
            return table_center_z


    def _perform_surface_detection_and_correction(self, source_id):
        """Perform liquid surface detection and Z-axis correction."""
        try:
            if not self.tube_interface:
                return
            

            # Read current liquid surface height
            current_height = self.tube_interface.get_liquid_height(source_id)
            if current_height is not None:
                logger.info(f" {source_id} current surface height: {current_height:.2f} mm")
            current_height = current_height + self.surface_height_margin    # margin to surface, from settings


            # Calculate distance from floor (table center Z)
            # TubeFactory is expected to have already loaded table.yaml
            # Verify if tube_interface.factory.table_config is accessible
            table_center_z = self._get_table_center_z()
            floor_height = -table_center_z
            print(f" [DEBUG] Floor height: {floor_height:.2f} mm")
            distance_from_floor = floor_height + current_height
            print(f" [DEBUG] Distance from reference(0) to water surface: {distance_from_floor:.2f} mm")


            # Read current robot Z from ScaraInterface
            current_z = self.interface_manager.scara.get_current_position()['z']
            print(f" [DEBUG] Z-axis current position: {current_z:.2f} mm")
            # Recalculate current_z in pipette+tip coordinate system
            current_z = current_z + self.interface_manager.scara.get_end_effector_offset('pipette', with_tip=True)['z']
            print(f" [DEBUG] Z-axis position after recalculation in Pipette+Tip coordinates: {current_z:.2f} mm")


            # Calculate move distance to predicted surface
            move_distance = distance_from_floor - current_z
            print(f" [DEBUG] Distance to move to water surface: {move_distance:.2f} mm")


            # Move by move_distance using offset move
            is_success = self.interface_manager.scara.move_offset('z', move_distance, speed=self.pre_surface_detection_z_axis_speed, skip_gripper_rotation=True)
            if not is_success:
                print(f" [DEBUG] Movement failed - did not reach predicted water surface position")
                return False
            print(f" [DEBUG] Movement completed - reached predicted water surface position")
  

            # Run hardware surface detection from current position
            detected_height = self._perform_surface_detection(speed=self.surface_detection_descent_speed)
            if detected_height:
                # Correct stored height based on detected surface
                success = self.tube_interface.set_detected_height(source_id, detected_height)
                if success:
                    logger.info(f" Surface detection correction completed: {detected_height:.2f} mm")
                else:
                    logger.warning(" Surface detection correction failed")
            else:
                logger.warning(" Surface detection failed - keeping current height")
                

        except Exception as e:
            logger.error(f" Surface detection error: {e}")
    

    def move_scara_down(self, target_z: float = None, speed: float = 1.0) -> bool:
        """
        Move the SCARA robot downward.
        

        Args:
            target_z (float, optional): Target Z position (mm, pipette+tip frame). None moves to ABSOLUTE_MIN_Z_POSITION.
            speed (float): Movement speed (default: 1.0)
        

        Returns:
            bool: True if movement succeeded
        """
        try:
            # Get current Z in pipette+tip coordinate frame
            current_pos = self.interface_manager.scara.get_current_position()
            current_z = current_pos['z'] + self.interface_manager.scara.get_end_effector_offset('pipette', with_tip=True)['z']
            print(f" [DEBUG] Z-axis position: {current_z:.2f} mm")
            

            # Use default if target_z not provided
            if target_z is None:
                target_z = ActionCommander.ABSOLUTE_MIN_Z_POSITION - current_z  # Offset to reach absolute minimum
                logger.info(f" Scara start: move {target_z:.2f}mm at speed {speed} (default: {ActionCommander.ABSOLUTE_MIN_Z_POSITION}mm)")
            else:
                # Convert absolute target Z to relative offset
                # target_z is in pipette+tip frame; offset is also in pipette+tip frame
                target_z = target_z - current_z
                logger.info(f" Scara start: move {target_z:.2f}mm at speed {speed} (target: {target_z + current_z:.2f}mm)")
            

            logger.info(f" Current Z: {current_z:.2f}mm → move distance: {target_z:.2f}mm")
            

            # Start SCARA move
            # move_offset is in robot coordinate system, but passing pipette+tip offset is fine
            # because offset is a relative distance (same in both coordinate systems)
            result = self.interface_manager.scara.move_offset('z', target_z, speed=speed, skip_gripper_rotation=True)
            if not result:
                logger.error(" Scara move failed")
                return False
            logger.info(" Scara move completed")
            return True
           

        except Exception as e:
            logger.error(f" Scara move error: {e}")
            return False
    

    def _perform_surface_detection(self, speed: float = 1.0):
        """
        Perform hardware surface detection.
        

        Args:
            source_id: Source ID
            target_z (float, optional): Target Z position (mm). None uses default -395mm.
            speed (float): Movement speed (default: 1.0)
        

        Thread structure:
        1. SCARA descent thread: moves to target Z at specified speed
        2. Surface detection thread: reads DAKEN status; stops SCARA on status 03 (surface detected)
        """
        

        if not (hasattr(self.interface_manager, 'daken') and self.interface_manager.daken):
            logger.error(" DakenInterface not found")
            return None
        

        if not (hasattr(self.interface_manager, 'scara') and self.interface_manager.scara):
            logger.error(" ScaraInterface not found")
            return None
        

        # Shared state
        surface_detected = threading.Event()  # Surface detection event
        detected_height = [None]  # Detected height (shared via list)
        error_occurred = threading.Event()  # Error flag
        descent_started = threading.Event() # Descent started flag
        descent_completed = threading.Event() # Descent completed flag
        

        # Helper: on failure, move_to_top then stop experiment
        def handle_failure_and_stop(reason: str):
            """On failure: move to top then stop experiment."""
            logger.error(f" {reason} - moving to top then stopping experiment")
            try:
                # Run move_to_top
                move_to_top_speed = getattr(self.action_commander, 'initial_position_move_to_top_speed', 50) if self.action_commander else 50
                logger.info(f" Moving to top due to failure... (speed: {move_to_top_speed})")
                result = self.interface_manager.scara.move_to_top(speed=move_to_top_speed)
                if result:
                    logger.info(" Move to top completed")
                else:
                    logger.warning(" Move to top failed (continuing)")
                

                # Stop experiment
                if self.action_commander:
                    self.action_commander.stop_execution()
                    logger.info(" Experiment stop completed")
            except Exception as e:
                logger.error(f" Error during failure handling: {e}")
               

        # Surface detection mode setup
        def detect_set_mode():
            try:
                logger.info(" Setting surface detection mode")


                # Refer to : test_pressure_sensing_action_commander.py
                # to set air pressure preparation to 60000
                result = self.interface_manager.daken.set_advanced_parameters(
                    first_suction=self.config_manager.get("daken_parameters", "surface_detection_mode", "first_suction") if self.config_manager else 2000,
                    air_pressure_prep=self.config_manager.get("daken_parameters", "surface_detection_mode", "air_pressure_prep") if self.config_manager else 60000,
                    second_suction=self.config_manager.get("daken_parameters", "surface_detection_mode", "second_suction") if self.config_manager else 10,
                    tip_eject=self.config_manager.get("daken_parameters", "surface_detection_mode", "tip_eject") if self.config_manager else 10484,
                    air_detection_speed=self.config_manager.get("daken_parameters", "surface_detection_mode", "air_detection_speed") if self.config_manager else 2599
                )
                if result != "OK":
                    logger.error(f" Advanced parameter set failed: {result}")
                    return False
                    

                # prepare_air_pump
                if self.interface_manager.daken.aspirate_first_air() != "01":
                    logger.error(" Air pump preparation failed")
                    return None
                if self.interface_manager.daken.read_air_pump_status() != "01":
                    logger.error(" Air pump status check failed")
                    # Move to top then stop experiment on failure
                    handle_failure_and_stop("Air pump status check failed")
                    return None
                if self.interface_manager.daken.set_detect_mode() != "OK":
                    logger.error(" Surface detection mode setup failed")
                    # Move to top then stop experiment on failure
                    handle_failure_and_stop("Surface detection mode setup failed")
                    return None
                return True


            except Exception as e:
                logger.error(f" Surface detection mode setup error: {e}")
                return False
        

        # SCARA descent thread (async)
        def descent_thread():
            try:
                logger.info(" Scara descent thread started")
                descent_started.set()
                # Descend at specified speed; no need to check completion (stopping mid-way is normal)
                self.move_scara_down(target_z=ActionCommander.ABSOLUTE_MIN_Z_POSITION, speed=speed)
                descent_completed.set()
                logger.info(" Scara descent completed or stopped")
            except Exception as e:
                logger.error(f" Scara descent thread error: {e}")
                # Attempt to stop SCARA on error
                try:
                    self.interface_manager.scara.stop_move()
                except:
                    pass
                error_occurred.set()
                descent_completed.set()
        

        # Surface detection function (regular function)
        def detect_surface():
            try:
                logger.info(" Surface detection started")


                timeout = self.surface_detection_timeout  # Timeout from settings
                start_time = time.time()
                

                # Variables for tracking descent position and speed
                last_z_position = initial_z
                last_position_time = start_time
                position_check_interval = 0.5  # Check position every 0.5 seconds
                last_position_check_time = start_time
                

                # Surface detection loop
                while True: #time.time() - start_time < timeout:
                    # Check pause/stop state
                    if self.action_commander is not None:
                        if self.action_commander.is_stopped:
                            logger.info(" Execution stopped, aborting surface detection.")
                            # Send stop command
                            self.interface_manager.scara.stop_move()
                            # Wait for robot to fully stop
                            self.interface_manager.scara.wait_for_movement_complete(timeout=self.movement_completion_timeout, action_commander=self.action_commander)
                            return None
                        # Keep waiting when paused (do not stop)
                        if self.action_commander.is_paused:
                            time.sleep(0.1)
                            continue
                    

                    # Check error flag
                    if error_occurred.is_set():
                        logger.error(" Error during descent")
                        # Stop SCARA on error
                        self.interface_manager.scara.stop_move()
                        # Wait for robot to fully stop
                        self.interface_manager.scara.wait_for_movement_complete(timeout=self.movement_completion_timeout, action_commander=self.action_commander)
                        return None
                    

                    # Descend by configured step distance
                    step_distance = self.surface_detection_descent_step
                    descent_speed = self.surface_detection_descent_speed
                    self.interface_manager.scara.move_offset('z', step_distance, speed=descent_speed, skip_gripper_rotation=True)
                    if not self.interface_manager.scara.wait_for_movement_complete(timeout=self.movement_completion_timeout, action_commander=self.action_commander):
                        logger.warning(" Robot stop timeout, continuing")
                        return None
                    logger.info(f" {abs(step_distance):.2f}mm descent completed ----------------------------------------------")


                    # Periodically read descent position and calculate speed
                    current_time = time.time()
                    if current_time - last_position_check_time >= position_check_interval:
                        try:
                            current_pos = self.interface_manager.scara.get_current_position()
                            if current_pos is not None:
                                current_z = current_pos['z']
                                elapsed_time = current_time - last_position_time
                                

                                if elapsed_time > 0 and abs(current_z - last_z_position) > 0.01:  # If moved > 0.01mm
                                    z_distance = last_z_position - current_z  # Descent distance (positive)
                                    velocity = z_distance / elapsed_time # mm/s
                                    

                                    total_elapsed = current_time - start_time
                                    total_distance = initial_z - current_z  # Total descent distance
                                    

                                    logger.info(f" Descent status: current Z={current_z:.2f}mm, "
                                              f"descent={total_distance:.2f}mm, "
                                              f"speed={velocity:.2f}mm/s, "
                                              f"elapsed={total_elapsed:.1f}s")
                                    

                                    last_z_position = current_z
                                    last_position_time = current_time
                                

                                last_position_check_time = current_time
                        except Exception as e:
                            logger.debug(f" Position read error (ignored): {e}")
                    

                    # Read DAKEN running status (d command)
                    status = self.interface_manager.daken.read_running_status()
                    

                    if status == "03":  # Surface detection success
                        logger.info(" Surface detection success! (03)")
                        

                        # Log final descent state
                        try:
                            final_pos = self.interface_manager.scara.get_current_position()
                            if final_pos is not None:
                                final_z = final_pos['z']
                                final_elapsed = time.time() - start_time
                                final_total_distance = initial_z - final_z
                                

                                if final_elapsed > 0:
                                    average_velocity = final_total_distance / final_elapsed
                                    logger.info(f" Final descent status: Z={final_z:.2f}mm, "
                                              f"total descent={final_total_distance:.2f}mm, "
                                              f"avg speed={average_velocity:.2f}mm/s, "
                                              f"elapsed={final_elapsed:.1f}s")
                        except Exception as e:
                            logger.debug(f" Final position read error (ignored): {e}")
                                              

                        # Correction move after surface detection (positive: rise, negative: descend)
                        self.interface_manager.scara.move_offset('z', self.surface_detection_rise_distance, speed=self.surface_detection_rise_speed, skip_gripper_rotation=True)
                        direction = "rise" if self.surface_detection_rise_distance >= 0 else "descent"
                        logger.info(f" ---------------- Surface detection correction done: {abs(self.surface_detection_rise_distance):.2f}mm {direction}")


                        # Wait for robot to fully stop
                        if self.interface_manager.scara.wait_for_movement_complete(timeout=2.0, action_commander=self.action_commander):
                            logger.info(" Robot stop completed")
                        else:
                            logger.warning(" Robot stop timeout, continuing")
    

                        # Calculate current height
                        current_pos = self.interface_manager.scara.get_current_position()
                        current_z = current_pos['z']
                        current_z = current_z + self.interface_manager.scara.get_end_effector_offset('pipette', with_tip=True)['z']
                        print(f" [DEBUG] Z-axis position after recalculation in Pipette+Tip coordinates: {current_z:.2f} mm")
                        # Calculate as surface height
                        table_center_z = -self._get_table_center_z()  # table.yaml z is absolute; convert to robot frame (negative)
                        detected_height[0] = abs(table_center_z - current_z)  # Height is absolute; calculate difference from table center
                        print(f" [DEBUG] Water surface detection height: {detected_height[0]:.2f} mm")
                        # Set event
                        surface_detected.set()




                        # to recover air pressure preparation
                        # First, move up to 10mm
                        self.interface_manager.scara.move_offset('z', self.surface_detection_return_distance, speed=self.surface_detection_return_speed, skip_gripper_rotation=True)
                        logger.info(f" Scara move completed - {abs(self.surface_detection_return_distance):.2f}mm {direction}")
                        # check if the robot is stopped
                        if not self.interface_manager.scara.wait_for_movement_complete(timeout=self.movement_completion_timeout, action_commander=self.action_commander):
                            logger.warning(" Robot stop timeout, continuing")
                            return None
                        logger.info(" Robot stop completed")


                        result = self.interface_manager.daken.set_advanced_parameters(
                            first_suction=self.config_manager.get("daken_parameters", "aspiration_mode", "first_suction") if self.config_manager else 2000,
                            air_pressure_prep=self.config_manager.get("daken_parameters", "aspiration_mode", "air_pressure_prep") if self.config_manager else 8192,
                            second_suction=self.config_manager.get("daken_parameters", "aspiration_mode", "second_suction") if self.config_manager else 10,
                            tip_eject=self.config_manager.get("daken_parameters", "aspiration_mode", "tip_eject") if self.config_manager else 10484,
                            air_detection_speed=self.config_manager.get("daken_parameters", "aspiration_mode", "air_detection_speed") if self.config_manager else 2599
                        )
                        if result != "OK":
                            logger.error(f" Advanced parameter set failed: {result}")
                            return None
                        logger.info(" [Detect -> Aspirate] Advanced parameter restore completed")


                        # first air aspirate
                        if self.interface_manager.daken.aspirate_first_air() != "01":
                            logger.error(" Air pump preparation failed")
                            return None
                        logger.info(" [Detect -> Aspirate] Air pump ready - first air aspirate")
                        # read air pump status
                        if self.interface_manager.daken.read_air_pump_status() != "01":
                            logger.error(" Air pump status check failed")
                            # Move to top then stop experiment on failure
                            handle_failure_and_stop("Air pump status check failed")
                            return None
                        logger.info(" [Detect -> Aspirate] Air pump status check done")
                        # spit all liquid
                        if self.interface_manager.daken.spit_liquid(0) != "01":
                            logger.error(" Liquid dispense failed")
                            return None
                        logger.info(" [Detect -> Aspirate] Liquid dispense mode done")


                        # move down to original position
                        self.interface_manager.scara.move_offset('z', -self.surface_detection_return_distance, speed=self.surface_detection_return_speed, skip_gripper_rotation=True)
                        if not self.interface_manager.scara.wait_for_movement_complete(timeout=self.movement_completion_timeout, action_commander=self.action_commander):
                            logger.warning(" Robot stop timeout, continuing")
                        logger.info(f" [Detect -> Aspirate] Scara move done - {abs(self.surface_detection_return_distance):.2f}mm {direction} - return to original position")
                        return detected_height[0]
                        

                    elif status == "04":  # Surface not detected yet
                        logger.debug(" Surface not detected (04) - continuing...")
                    

                    else:
                        logger.debug(f" Current status: {status}")
                    

                    time.sleep(self.surface_detection_check_interval)  # Check interval from settings
                

                # Timeout
                logger.warning(f" Surface detection timeout ({self.surface_detection_timeout}s)")
                # Stop SCARA on timeout
                self.interface_manager.scara.stop_move()
                # Wait for robot to fully stop
                self.interface_manager.scara.wait_for_movement_complete(timeout=self.movement_completion_timeout, action_commander=self.action_commander)
                error_occurred.set()
                return None
                

            except Exception as e:
                logger.error(f" Surface detection error: {e}")
                # Stop SCARA on error
                try:
                    self.interface_manager.scara.stop_move()
                    self.interface_manager.scara.wait_for_movement_complete(timeout=self.movement_completion_timeout, action_commander=self.action_commander)
                except:
                    pass
                error_occurred.set()
                return None
        # Set surface detection mode
        logger.info(" Surface detection starting")


        if not detect_set_mode():
            logger.error(" Surface detection mode setup failed")
            handle_failure_and_stop("Surface detection mode setup failed")
            return None
        

        # Record initial SCARA height before starting
        initial_z = self._get_initial_scara_z()
        if initial_z is None:
            logger.error(" Cannot read initial Scara height")
            return None
        

        try:
            # Call surface detection function (regular function)
            detect_surface()
            

            # Check result
            if surface_detected.is_set():
                logger.info(f" Surface detection completed: {detected_height[0]:.2f}mm")
                return detected_height[0]
            else:
                logger.warning(" Surface detection failed or timeout")
                return None
                

        except Exception as e:
            logger.error(f" Exception during surface detection: {e}")
            # Stop SCARA on exception
            try:
                self.interface_manager.scara.stop_move()
                self.interface_manager.scara.wait_for_movement_complete(timeout=self.movement_completion_timeout, action_commander=self.action_commander)
            except:
                pass
            return None
    

    def _consume_liquid_after_successful_aspiration(self, source_id, amount):
        """Update tube liquid level after successful aspiration."""
        try:
            if not self.tube_interface or not source_id:
                return
            

            # Execute liquid consumption
            success = self.tube_interface.consume_liquid_by_volume(source_id, amount)
            if success:
                logger.info(f" {source_id} consumed {amount} ul completed")
                

                # Query detailed status after consumption
                status = self.tube_interface.get_item_status(source_id)
                if status:
                    # Log detailed status
                    current_height = status.get('height_mm', 0)
                    current_volume = status.get('volume_ul', 0)
                    max_volume = status.get('max_volume_ul', 0)
                    remaining_volume = status.get('remaining_volume_ul', 0)
                    fill_percentage = status.get('fill_percentage', 0)
                    

                    logger.info(f" {source_id} current status:")
                    logger.info(f" - Current height: {current_height:.2f} mm")
                    logger.info(f" - Current volume: {current_volume:.2f} ul")
                    logger.info(f" - Remaining volume: {remaining_volume:.2f} ul")
                    logger.info(f" - Max volume: {max_volume:.2f} ul")
                    logger.info(f" - Fill rate: {fill_percentage:.1f}%")
                

                # Update tube status via GUI callback
                if self.gui_callback:
                    self.gui_callback("tube_status_update", source_id)
            else:
                logger.warning(f" {source_id} liquid consumption failed")
                

        except Exception as e:
            logger.error(f" Liquid consumption error: {e}")


    def _add_liquid_after_successful_dispense(self, source_id, amount):
        """Update tube liquid level after successful dispense."""
        try:
            if not self.tube_interface or not source_id:
                return
            

            # Execute liquid addition
            success = self.tube_interface.add_liquid_by_volume(source_id, amount)
            if success:
                logger.info(f" {source_id} added {amount} ul completed")
                

                # Query detailed status after addition
                status = self.tube_interface.get_item_status(source_id)
                if status:
                    # Log detailed status
                    current_height = status.get('height_mm', 0)
                    current_volume = status.get('volume_ul', 0)
                    max_volume = status.get('max_volume_ul', 0)
                    remaining_volume = status.get('remaining_volume_ul', 0)
                    fill_percentage = status.get('fill_percentage', 0)
                    

                    logger.info(f" {source_id} current status:")
                    logger.info(f" - Current height: {current_height:.2f} mm")
                    logger.info(f" - Current volume: {current_volume:.2f} ul")
                    logger.info(f" - Remaining volume: {remaining_volume:.2f} ul")
                    logger.info(f" - Max volume: {max_volume:.2f} ul")
                    logger.info(f" - Fill rate: {fill_percentage:.1f}%")
                

                # Update tube status via GUI callback
                if self.gui_callback:
                    self.gui_callback("tube_status_update", source_id)
            else:
                logger.warning(f" {source_id} liquid add failed")
                

        except Exception as e:
            logger.error(f" Liquid add error: {e}")


    def _wait_for_scara_descent(self, initial_z: float, target_descent_mm: float,
                                 error_occurred: threading.Event, timeout: float = None) -> bool:
        """
        Wait until SCARA has descended the specified distance.
        

        Args:
            initial_z (float): Initial Z height (pipette+tip frame)
            target_descent_mm (float): Target descent distance (mm)
            error_occurred (threading.Event): Error flag
            timeout (float): Maximum wait time in seconds; None = use config value
            

        Returns:
            bool: True if target reached; False on timeout or error
        """
        if timeout is None:
            timeout = self.scara_descent_wait_timeout
        target_z = initial_z - target_descent_mm
        logger.info(f" Initial Z: {initial_z:.2f}mm, target: {target_z:.2f}mm")
        logger.info(f" Waiting for Scara to descend {target_descent_mm}mm...")
        

        start_time = time.time()
        check_interval = self.general_check_interval  # Check interval from settings
        

        while True:
            # Check timeout
            if timeout is None:
                timeout = self.scara_descent_wait_timeout
            if time.time() - start_time > timeout:
                logger.warning(f" Descent wait timeout ({timeout}s)")
                return False
            

            # Check error flag
            if error_occurred.is_set():
                logger.error(" Error during descent")
                return False
            

            # Read current height
            current_position = self.interface_manager.scara.get_current_position()
            if current_position is None:
                logger.warning(" Cannot read position, retrying...")
                time.sleep(check_interval)
                continue
            

            current_z = current_position['z']
            # Recalculate in pipette+tip coordinate frame
            offset_z = self.interface_manager.scara.get_end_effector_offset('pipette', with_tip=True)['z']
            current_z = current_z + offset_z
            

            # Debug: periodically log current state (every 1 second)
            elapsed_time = time.time() - start_time
            if int(elapsed_time * 10) % 10 == 0:  # Output every 1 second
                logger.debug(f" Waiting for descent: current Z={current_z:.2f}mm, target Z={target_z:.2f}mm, diff={current_z - target_z:.2f}mm, elapsed={elapsed_time:.1f}s")
            

            # Check if target height reached
            # Allow small tolerance (0.1mm) for floating point errors
            if current_z <= target_z + 0.1:
                logger.info(f" Target height reached: {current_z:.2f}mm (target: {target_z:.2f}mm, diff: {current_z - target_z:.2f}mm)")
                return True
            

            # Target height not yet reached
            time.sleep(check_interval)


    def _get_initial_scara_z(self) -> float:
        """
        Read SCARA current Z height and convert to pipette+tip coordinate frame.
        

        Returns:
            float: Current Z in pipette+tip frame (mm), or None on failure
        """
        try:
            initial_position = self.interface_manager.scara.get_current_position()
            if initial_position is None:
                logger.error(" Cannot read initial Scara position")
                return None
            

            initial_z = initial_position['z']
            # Recalculate in pipette+tip coordinate frame
            initial_z = initial_z + self.interface_manager.scara.get_end_effector_offset('pipette', with_tip=True)['z']
            return initial_z
        except Exception as e:
            logger.error(f" Initial Scara height read error: {e}")
            return None


    def _perform_aspiration_surface_detection(self, source_id, amount: float = None, aspirate_amount: float = None):
        '''
        Starting from detected surface: descend while aspirating.
        Steps:
            1. Read descent speed matching tube consumption rate for source_id
            2. Descend SCARA at that speed
            3. Aspirate configured volume simultaneously; move to top when done
        '''
        try:
            if not self.tube_interface:
                logger.error(" Tube Interface not found")
                return False
            

            if not self.interface_manager.connected_interfaces.get('scara'):
                logger.error(" SCARA interface is not connected")
                return False
            

            if not self.interface_manager.connected_interfaces.get('daken'):
                logger.error(" DAKEN interface not connected")
                return False
            

            # Use default if amount not provided
            if amount is None:
                amount = self.aspiration_amount_default  # Default value
                logger.warning(f" amount not specified, using default {amount}μL")
            

            # 1. Read tube status and descent speed for source_id
            item_status = self.tube_interface.get_item_status(source_id)
            if not item_status:
                logger.error(f" Cannot get {source_id} status")
                return False
            

            # Get Tube Manager (for descent distance calculation)
            manager = self.tube_interface.factory.get_tube_manager_by_table_name(source_id)
            if not manager:
                logger.error(f" Tube Manager not found for {source_id}")
                return False
            

            # Get current height and volume
            current_height_mm = manager.current_height_mm
            current_volume_ul = manager.current_volume_ul
            

            # Calculate target volume (current volume - aspiration volume)
            target_volume_ul = current_volume_ul - amount
            is_insufficient_volume = target_volume_ul < 0
            if is_insufficient_volume:
                logger.warning(f" Aspiration volume ({amount}μL) exceeds current ({current_volume_ul:.2f}μL). Aspirating available amount.")
                # Aspirate only available amount
                actual_amount = current_volume_ul
                target_volume_ul = 0  # Remaining amount becomes 0
            else:
                actual_amount = amount
            

            # Calculate target height
            target_height_mm = manager._calculate_height_from_volume(target_volume_ul)
            

            # Calculate descent distance (from current height to target height)
            required_descent_mm = current_height_mm - target_height_mm
            logger.info(f" Descent distance for {actual_amount}μL aspiration:")
            logger.info(f" - Current height: {current_height_mm:.2f} mm, volume: {current_volume_ul:.2f} μL")
            logger.info(f" - Target height: {target_height_mm:.2f} mm, volume: {target_volume_ul:.2f} μL")
            logger.info(f" - Descent distance: {required_descent_mm:.2f} mm")
            

            # Read aspiration speed (consumption_rate_mm_s)
            consumption_rate_mm_s = item_status.get('consumption_rate_mm_s', self.config_manager.get("speed", "aspiration_descent_speed") if self.config_manager else 1.0) # mm/s
            descent_speed = consumption_rate_mm_s  # Descent speed (mm/s)
            

            # Shared state
            descent_started = threading.Event()  # Descent start flag
            descent_completed = threading.Event() # Descent completed flag (can be stopped mid-descent)
            error_occurred = threading.Event()  # Error flag
            

            # Record initial SCARA height before starting thread
            initial_z = self._get_initial_scara_z()
            if initial_z is None:
                logger.error(" Cannot read initial Scara height")
                return False
            

            # Calculate target Z (descend by calculated distance from current position)
            target_z = initial_z - required_descent_mm
            

            # Check and clamp to Z axis limit
            if target_z < ActionCommander.ABSOLUTE_MIN_Z_POSITION:
                logger.warning(f" Target Z ({target_z:.2f}mm) below limit ({ActionCommander.ABSOLUTE_MIN_Z_POSITION}mm). Clamping to limit.")
                target_z = ActionCommander.ABSOLUTE_MIN_Z_POSITION
                # Recalculate actual descent distance based on clamped Z position
                required_descent_mm = initial_z - target_z
                logger.info(f" Clamped descent distance: {required_descent_mm:.2f} mm")
            

            logger.info(f" Descent target: {initial_z:.2f} mm → {target_z:.2f} mm (descent: {required_descent_mm:.2f} mm)------------------------")
            

            # 2. SCARA descent thread (async)
            def descent_thread():
                try:
                    logger.info(" Scara descent thread started")
                    descent_started.set()
                    # Descend by calculated distance (not absolute minimum)
                    self.move_scara_down(target_z=target_z, speed=descent_speed)
                    descent_completed.set()
                    logger.info(" Scara descent completed or stopped")
                except Exception as e:
                    logger.error(f" Scara descent thread error: {e}")
                    error_occurred.set()
                    descent_completed.set()
            

            # Start SCARA descent thread
            descent_thread_obj = threading.Thread(target=descent_thread, daemon=True)
            descent_thread_obj.start()
            logger.info(" Scara descent thread starting")
            

            # Wait for descent to start
            if not descent_started.wait(timeout=self.movement_completion_timeout):
                logger.error(" Scara descent start timeout")
                return False
            

            # Wait until pipette has descended 0.5mm (confirm descent started)
            # Short timeout (only for descent start confirmation)
            check_timeout = min(5.0, self.scara_descent_wait_timeout)  # Max 5 seconds
            if not self._wait_for_scara_descent(initial_z, target_descent_mm=self.descent_start_check_distance, error_occurred=error_occurred, timeout=check_timeout):
                logger.warning(" Descent start check failed (0.5mm timeout). Continuing.")
                # Continue even on timeout (descent may have already started)
            

            logger.info(" Liquid aspiration ready!----------------------------------------------")
            

            # 3. Run aspiration sequentially
            try:
                # Add 30uL to actual_amount (except when insufficient volume)
                if is_insufficient_volume:
                    # Insufficient: aspirate only remaining (no +30uL)
                    actual_aspirate_amount = actual_amount
                    logger.info(f" Liquid aspiration start: {actual_aspirate_amount}μL (remaining only, no +30μL)")
                else:
                    # Normal: add 30uL to amount
                    actual_aspirate_amount = actual_amount + 30
                    logger.info(f" Liquid aspiration start: {actual_aspirate_amount}μL (original: {actual_amount}μL + 30μL)")
                

                aspiration_result = self.interface_manager.daken.aspirate_liquid(actual_aspirate_amount)
                

                if aspiration_result == "01":
                    logger.info(f" Liquid aspiration done: {actual_aspirate_amount}μL (original: {actual_amount}μL{' + 30μL' if not is_insufficient_volume else ''})")
                    # Stop immediately after aspiration
                    self.interface_manager.scara.stop_move()
                    logger.info(" Scara move stopped (aspiration done)")
                    

                    # Wait for robot to fully stop
                    if self.interface_manager.scara.wait_for_movement_complete(timeout=2.0, action_commander=self.action_commander):
                        logger.info(" Robot stop completed")
                    else:
                        logger.warning(" Robot stop timeout, continuing")
                    

                    # Update tube liquid level (consume actual aspirated amount)
                    if self.tube_interface:
                        self._consume_liquid_after_successful_aspiration(source_id, actual_aspirate_amount)
                        # Store source_id of last take action (for 30uL decision in dispose)
                        self.last_take_source_id = source_id
                else:
                    logger.warning(f" Aspiration result: {aspiration_result}")
                    # Stop on aspiration failure too
                    self.interface_manager.scara.stop_move()
                    return False
                    

            except Exception as e:
                logger.error(f" Descent/aspiration error: {e}")
                error_occurred.set()
                self.interface_manager.scara.stop_move()
                return False
            

            # Check result
            if error_occurred.is_set():
                logger.error(" Error during descent and aspiration")
                return False
            

           

            return True
            

        except Exception as e:
            logger.error(f" Surface detection and aspiration error: {e}")
            return False


class ActionCommander:
    """
    Main class of the integrated robot control system.
    Reads JSON command files and executes all robot interfaces in sequence.
    """
    

    # Absolute minimum Z position (mm) - overridable from config
    ABSOLUTE_MIN_Z_POSITION = -395
    

    def __init__(self, json_file_path: Optional[str] = None, interactive_mode: bool = False, gui_callback=None, tube_interface=None):
        """
        Initialize ActionCommander.
        

        Args:
            json_file_path (Optional[str]): Path to JSON command file (None skips loading)
            interactive_mode (bool): If True, waits for user input before each command
            gui_callback: GUI message callback function
            tube_interface: Tube Interface instance
        """
        # Initialize settings manager
        if HAS_CONFIG_MANAGER:
            try:
                self.config_manager = RobotConstantsManager()
            except Exception as e:
                logger.warning(f" Config manager init failed: {e}. Using default values.")
                self.config_manager = None
        else:
            self.config_manager = None
        

        # Load constants from config
        self._load_constants_from_config()
        

        self.json_file_path = json_file_path
        self.interactive_mode = interactive_mode
        self.command_parser = CommandParser(json_file_path)
        self.interface_manager = InterfaceManager(gui_callback=gui_callback)
        self.tube_interface = tube_interface  # Tube Interface
        # Get MEA Stack Manager (optional)
        mea_stack_manager = None
        if hasattr(self, 'mea_stack_manager'):
            mea_stack_manager = self.mea_stack_manager
        

        self.command_executor = CommandExecutor(
            self.interface_manager,
            self.tube_interface,
            gui_callback,
            action_commander=self,
            config_manager=self.config_manager,
            mea_stack_manager=mea_stack_manager
        )
        

        self.is_initialized = False
        self.execution_stats = {
            'total_commands': 0,
            'successful_commands': 0,
            'failed_commands': 0,
            'skipped_commands': 0
        }
        

        # Execution state flags
        self.is_paused = False
        self.is_stopped = False
        

        # Progress and GUI callbacks
        self.progress_callback = None
        

        # GUI callback
        self.gui_callback = None
    

    def _load_constants_from_config(self):
        """Load constant values from config manager."""
        if self.config_manager:
            # Absolute minimum Z position
            abs_min_z = self.config_manager.get("position", "absolute_min_z_position")
            if abs_min_z is not None:
                ActionCommander.ABSOLUTE_MIN_Z_POSITION = abs_min_z
                logger.info(f" {tr('message.absolute_min_z.loaded', abs_min_z=abs_min_z)}")
            

            # Initial robot positions
            initial_pos = self.config_manager.get("position", "initial_position")
            if initial_pos:
                self.initial_position = initial_pos
                logger.info(f" {tr('message.initial_position.loaded')}")
            else:
                # Default values
                self.initial_position = {
                    'scara': {'x': 420, 'y': 0, 'z': 0, 'r': 0},
                    'servo': {'angle': 60},
                    'gripper': {'distance': 20.0, 'speed': 50}
                }
            

            # Speed settings for initial position
            self.initial_position_move_to_top_speed = self.config_manager.get("speed", "initial_position_move_to_top_speed") or 50
            self.initial_position_speed = self.config_manager.get("speed", "initial_position_speed") or 50
        else:
            # Default values
            self.initial_position = {
                'scara': {'x': 420, 'y': 0, 'z': 0, 'r': 0},
                'servo': {'angle': 60},
                'gripper': {'distance': 20.0, 'speed': 50}
            }
            self.initial_position_move_to_top_speed = 50
            self.initial_position_speed = 50
    

    def set_tube_interface(self, tube_interface):
        """
        Set Tube Interface (can also be set at runtime).
        

        Args:
            tube_interface: Tube Interface instance
        """
        self.tube_interface = tube_interface
        if self.command_executor:
            self.command_executor.tube_interface = tube_interface
        logger.info(" Tube Interface setup completed")
    

    def set_gui_callback(self, gui_callback):
        """
        Set GUI message callback function.
        

        Args:
            gui_callback: Function called when sending GUI messages.
                         Signature: gui_callback(message: str, source_id: str = None)
        """
        self.gui_callback = gui_callback
        

        # Pass GUI callback to CommandExecutor
        if self.command_executor:
            self.command_executor.gui_callback = gui_callback
        

        # Pass GUI callback to InterfaceManager
        if self.interface_manager:
            self.interface_manager.gui_callback = gui_callback
            

        # Pass GUI callback to MeasurementInterface
        if hasattr(self.interface_manager, 'measurement') and self.interface_manager.measurement:
            self.interface_manager.measurement.gui_callback = gui_callback
    

    def set_progress_callback(self, callback):
        """
        Set progress update callback function.
        

        Args:
            callback: Function called on progress updates.
                     Signature: callback(progress_percent, current_command, total_commands)
        """
        self.progress_callback = callback
    

    def initialize(self) -> bool:
        """
        Initialize the system.
        

        Returns:
            bool: True if initialization succeeded
        """
        logger.info(f" {tr('message.action_commander.initializing')}")
        

        # Reload config to apply latest settings
        if self.config_manager:
            self.config_manager.reload()
            # Reload ActionCommander constants (ABSOLUTE_MIN_Z_POSITION, initial_position, etc.)
            self._load_constants_from_config()
            # Reload CommandExecutor constants
            if self.command_executor:
                self.command_executor._load_constants()
        

        # Load JSON command file (continue even if file is absent)
        if not self.command_parser.load_commands():
            logger.warning(f" {tr('message.command_file.load_failed')}. Continuing with empty command list.")
        

        # Connect all interfaces
        if not self.interface_manager.connect_all():
            logger.error(f" {tr('message.interface.connection_failed')}")
            return False
        

        self.is_initialized = True
        logger.info(f" {tr('message.action_commander.initialized')}")
        

        # After initialization: rise Z to top, then move to initial position
        if self.interface_manager.connected_interfaces.get('scara', False):
            try:
                logger.info(f" {tr('message.moving_to_top_after_init')}")
                # Rise Z from current position to top
                move_to_top_speed = getattr(self, 'initial_position_move_to_top_speed', 50)
                result = self.interface_manager.scara.move_to_top(speed=move_to_top_speed)
                if not result:
                    logger.warning(f" {tr('message.moving_to_top_failed')}")
                else:
                    logger.info(f" {tr('message.moved_to_top')}")
                    import time
                    time.sleep(0.5)  # Wait for move completion
                

                # Move to initial default position
                logger.info(f" {tr('message.moving_to_initial')}")
                if not self.set_initial_position():
                    logger.warning(f" {tr('message.moving_to_initial_failed')}")
                else:
                    logger.info(f" {tr('message.moved_to_initial')}")
            except Exception as e:
                logger.warning(f" Error during post-init position move: {e} (continuing)")
        

        return True
    

    def pause_execution(self):
        """Pause execution."""
        self.is_paused = True
        logger.info(" Execution paused.")
        

        # Stop robot movement immediately
        if self.interface_manager.connected_interfaces.get('scara', False):
            try:
                self.interface_manager.scara.stop_move()
                logger.info(" Sending robot move stop command")
            except Exception as e:
                logger.warning(f" Error sending robot stop command: {e}")
    

    def resume_execution(self):
        """Resume execution."""
        self.is_paused = False
        logger.info(" Execution resumed.")
    

    def reconnect_systems(self) -> bool:
        """
        Reconnect Measurement and JIG systems.
        

        Returns:
            bool: True if all reconnections succeeded
        """
        logger.info(" System reconnection starting...")
        

        try:
            # Reconnect via ConnectionManager
            measurement_system = self.interface_manager.connection_manager.get_or_create_connection(
                'measurement',
                port='/dev/ttyUSB0'
            )
            

            jig_controller = self.interface_manager.connection_manager.get_or_create_connection(
                'jig',
                port='/dev/ttyACM1'
            )
            

            # Check reconnection results
            measurement_success = measurement_system is not None
            jig_success = jig_controller is not None
            

            if measurement_success:
                # Update MeasurementInterface
                if not self.interface_manager.measurement:
                    self.interface_manager.measurement = MeasurementInterface(gui_callback=self.gui_callback)
                

                self.interface_manager.measurement.measurement_system = measurement_system
                self.interface_manager.measurement.is_connected = True
                self.interface_manager.connected_interfaces['measurement'] = True
                logger.info(" Measurement system reconnected")
            else:
                logger.warning(" Measurement system reconnect failed")
                self.interface_manager.connected_interfaces['measurement'] = False
            

            if jig_success:
                # Update JIG controller
                self.interface_manager.jig = jig_controller
                self.interface_manager.connected_interfaces['jig'] = True
                logger.info(" JIG system reconnected")
            else:
                logger.warning(" JIG system reconnect failed")
                self.interface_manager.connected_interfaces['jig'] = False
            

            # Overall reconnection result
            total_success = measurement_success and jig_success
            if total_success:
                logger.info(" All systems reconnected")
            else:
                logger.warning(" Some systems reconnect failed")
            

            return total_success
            

        except Exception as e:
            logger.error(f" System reconnection error: {e}")
            return False
    

    def get_connection_status(self) -> Dict[str, Any]:
        """
        Query current connection status.
        

        Returns:
            Dict[str, Any]: Connection status information
        """
        try:
            # Query ConnectionManager status
            connection_status = self.interface_manager.connection_manager.get_connection_status()
            

            # Combine with InterfaceManager status
            status = {
                'interfaces': self.interface_manager.connected_interfaces.copy(),
                'connections': connection_status,
                'timestamp': time.time()
            }
            

            return status
            

        except Exception as e:
            logger.error(f" Connection status query error: {e}")
            return {
                'interfaces': self.interface_manager.connected_interfaces.copy(),
                'connections': {},
                'error': str(e),
                'timestamp': time.time()
            }
    

    def stop_execution(self):
        """Stop execution."""
        self.is_stopped = True
        self.is_paused = False
        logger.info(" Execution stopped.")
        

        # Stop robot movement immediately
        if self.interface_manager.connected_interfaces.get('scara', False):
            try:
                self.interface_manager.scara.stop_move()
                logger.info(" Sending robot move stop command")
            except Exception as e:
                logger.warning(f" Error sending robot stop command: {e}")
    

    def set_initial_position(self) -> bool:
        """
        Move all robots to their initial positions.
        

        Returns:
            bool: True if all initial positions were set successfully
        """
        logger.info(" Starting initial position setup...")
        

        # Safety guard: use default values if attribute is missing
        move_to_top_speed = getattr(self, 'initial_position_move_to_top_speed', 50)
        initial_speed = getattr(self, 'initial_position_speed', 50)
        

        success_count = 0
        total_actions = 0
        

        # Move SCARA to initial position
        if self.interface_manager.connected_interfaces['scara']:
            total_actions += 1
            try:
                scara_pos = self.initial_position['scara']
                logger.info(f" SCARA initial position setup: X={scara_pos['x']}, Y={scara_pos['y']}, Z={scara_pos['z']}, R={scara_pos['r']}")
                

                # Skip gripper rotation if current end effector is pipette
                skip_gripper_rotation = (self.interface_manager.scara.current_end_effector == 'pipette')


                # Move to top first for safety
                logger.info(" Moving to top position for safety...")
                result = self.interface_manager.scara.move_to_top(speed=move_to_top_speed)
                if not result:
                    logger.error(" SCARA move to top failed")
                    return False
                

                result = self.interface_manager.scara.move_to_xyz(
                    x=scara_pos['x'],
                    y=scara_pos['y'],
                    z=scara_pos['z'],
                    r=scara_pos['r'],
                    speed=initial_speed,
                    skip_gripper_rotation=skip_gripper_rotation
                )
                

                if result.get('success', False):
                    success_count += 1
                    logger.info(" SCARA initial position setup completed")
                else:
                    logger.error(f" SCARA initial position setup failed: {result.get('message', 'Unknown error')}")
                    

            except Exception as e:
                logger.error(f" SCARA initial position setup error: {e}")
        

        # Move Servo to initial position
        if self.interface_manager.connected_interfaces['servo']:
            total_actions += 1
            try:
                servo_angle = self.initial_position['servo']['angle']
                logger.info(f" Servo initial position setup: {servo_angle}°")
                

                result = self.interface_manager.servo.move_to_angle(servo_angle, wait_time=2.0)
                

                if result:
                    success_count += 1
                    logger.info(" Servo initial position setup completed")
                else:
                    logger.error(" Servo initial position setup failed")
                    

            except Exception as e:
                logger.error(f" Servo initial position setup error: {e}")
        

        # Move Gripper to initial position (open)
        if self.interface_manager.connected_interfaces['gripper']:
            # Skip if current end effector is not gripper
            if self.interface_manager.scara.current_end_effector != 'gripper':
                logger.warning(f" Skipping Gripper initial position setup: current_end_effector={self.interface_manager.scara.current_end_effector} (not gripper)")
            else:
                total_actions += 1
                try:
                    gripper_config = self.initial_position['gripper']
                    logger.info(f" Gripper initial position setup: open (distance: {gripper_config['distance']}mm)")
                    

                    result = self.interface_manager.gripper.open(
                        distance=gripper_config['distance'],
                        speed=gripper_config['speed']
                    )
                

                    if result:
                        success_count += 1
                        logger.info(" Gripper initial position setup completed")
                    else:
                        logger.error(" Gripper initial position setup failed")
                        

                except Exception as e:
                    logger.error(f" Gripper initial position setup error: {e}")
        

        # Result summary
        if success_count == total_actions and total_actions > 0:
            logger.info(f" All robot initial position setup completed ({success_count}/{total_actions})")
            return True
        elif success_count > 0:
            logger.warning(f" Partial initial position setup ({success_count}/{total_actions})")
            return True
        else:
            logger.error(" Initial position setup failed")
            return False
    

    def return_to_initial_position(self) -> bool:
        """
        Return all robots to their initial positions.
        

        Returns:
            bool: True if all robots returned successfully
        """
        logger.info(" Starting return to initial position...")
        

        # Safety guard: use default values if attribute is missing
        move_to_top_speed = getattr(self, 'initial_position_move_to_top_speed', 50)
        initial_speed = getattr(self, 'initial_position_speed', 50)
        

        success_count = 0
        total_actions = 0
        

        # Return SCARA to initial position
        if self.interface_manager.connected_interfaces['scara']:
            total_actions += 1
            try:
                scara_pos = self.initial_position['scara']
                logger.info(f" SCARA return to initial position: X={scara_pos['x']}, Y={scara_pos['y']}, Z={scara_pos['z']}, R={scara_pos['r']}")
                

                # Skip gripper rotation if current end effector is pipette
                skip_gripper_rotation = (self.interface_manager.scara.current_end_effector == 'pipette')


                # move to top first
                result = self.interface_manager.scara.move_to_top(speed=move_to_top_speed)
                if not result:
                    logger.error(" SCARA move to top failed")
                    return False
                

                result = self.interface_manager.scara.move_to_xyz(
                    x=scara_pos['x'],
                    y=scara_pos['y'],
                    z=scara_pos['z'],
                    r=scara_pos['r'],
                    speed=initial_speed,
                    skip_gripper_rotation=skip_gripper_rotation
                )
                

                if result.get('success', False):
                    success_count += 1
                    logger.info(" SCARA return to initial position completed")
                else:
                    logger.error(f" SCARA return to initial position failed: {result.get('message', 'Unknown error')}")
                    

            except Exception as e:
                logger.error(f" SCARA return to initial position error: {e}")
        

        # Return Servo to initial position
        if self.interface_manager.connected_interfaces['servo']:
            total_actions += 1
            try:
                servo_angle = self.initial_position['servo']['angle']
                logger.info(f" Servo return to initial position: {servo_angle}°")
                

                result = self.interface_manager.servo.move_to_angle(servo_angle, wait_time=2.0)
                

                if result:
                    success_count += 1
                    logger.info(" Servo return to initial position completed")
                else:
                    logger.error(" Servo return to initial position failed")
                    

            except Exception as e:
                logger.error(f" Servo return to initial position error: {e}")
        

        # Return Gripper to initial position (open)
        if self.interface_manager.connected_interfaces['gripper']:
            # Skip if current end effector is not gripper
            if self.interface_manager.scara.current_end_effector != 'gripper':
                logger.warning(f" Gripper return to initial position skipped: current_end_effector={self.interface_manager.scara.current_end_effector} (not gripper)")
            else:
                total_actions += 1
                try:
                    gripper_config = self.initial_position['gripper']
                    logger.info(f" Gripper return to initial position: open (distance: {gripper_config['distance']}mm)")
                    

                    result = self.interface_manager.gripper.open(
                        distance=gripper_config['distance'],
                        speed=gripper_config['speed']
                    )
                

                    if result:
                        success_count += 1
                        logger.info(" Gripper return to initial position completed")
                    else:
                        logger.error(" Gripper return to initial position failed")
                        

                except Exception as e:
                    logger.error(f" Gripper return to initial position error: {e}")
        

        # Result summary
        if success_count == total_actions and total_actions > 0:
            logger.info(f" All robot initial position return completed ({success_count}/{total_actions})")
            return True
        elif success_count > 0:
            logger.warning(f" Partial return to initial position ({success_count}/{total_actions})")
            return True
        else:
            logger.error(" Return to initial position failed")
            return False
    

    def run_all_commands(self) -> bool:
        """
        Execute all commands in sequence.
        

        Returns:
            bool: True if all commands succeeded
        """
        if not self.is_initialized:
            logger.error(" System not initialized. Call initialize() first.")
            return False
        

        # 1. Set initial position
        logger.info(" Setting initial position before command execution...")
        if not self.set_initial_position():
            logger.warning(" Initial position setup failed but continuing command execution.")
        

        commands = self.command_parser.commands
        self.execution_stats['total_commands'] = len(commands)
        

        # Debug: check move_end_effector command parameters at run_all_commands start
        for i, cmd in enumerate(commands):
            if (cmd.get('function') == 'ScaraInterface.move_end_effector' and
                cmd.get('type') == 'equip' and
                cmd.get('action') == 'move_xy_position'):
                params = cmd.get('parameters', {})
                logger.info(f" [DEBUG] run_all_commands start - command #{i} params:")
                logger.info(f" - parameters type: {type(params)}")
                logger.info(f" - parameters keys: {list(params.keys()) if isinstance(params, dict) else 'N/A'}")
                logger.info(f" - calibration_angles: {params.get('calibration_angles')}")
                logger.info(f" - tool_name: {params.get('tool_name')}")
                logger.info(f" - grid_row: {params.get('grid_row')}")
                logger.info(f" - grid_col: {params.get('grid_col')}")
                break  # Check only the first occurrence
        

        logger.info(f" Starting execution of all commands: {len(commands)} commands")
        logger.info("=" * 60)
        

        for i, command in enumerate(commands, 1):
            # Check stop state
            if self.is_stopped:
                logger.info(" Execution stopped.")
                break
            

            # Wait while paused
            while self.is_paused and not self.is_stopped:
                time.sleep(0.1)  # Wait 100ms
            

            # Recheck stop state (in case stopped while paused)
            if self.is_stopped:
                logger.info(" Stopped while paused.")
                break
            

            logger.info(f" [{i}/{len(commands)}] Processing command...")
            

            # Validate command
            if not self.command_parser.validate_command(command):
                command_name = command.get('name') or command.get('action', 'Unknown')
                logger.warning(f" Command skipped: {command_name}")
                self.execution_stats['skipped_commands'] += 1
                continue
            

            # Wait for user input
            command_name = command.get('name') or command.get('action', 'Unknown')
            command_type = command.get('type', 'unknown')
            description = command.get('description', '')
            

            print(f"\n{'='*60}")
            print(f" Executing next command:")
            print(f" Type: {command_type}")
            print(f" Name: {command_name}")
            if description:
                print(f" Description: {description}")
            print(f"{'='*60}")
            

            # Wait for user input only in interactive mode
            if self.interactive_mode:
                input("Press Enter to execute the command...")
            

            # Execute command
            success = self.command_executor.execute_command(command)
            

            if success:
                self.execution_stats['successful_commands'] += 1
            else:
                self.execution_stats['failed_commands'] += 1
            

            # Call progress callback
            if self.progress_callback:
                progress_percent = int((i / len(commands)) * 100)
                self.progress_callback(progress_percent, i, len(commands))
            

            # Wait between commands
            time.sleep(0.5)
        

        # Print execution result summary
        self._print_execution_summary()
        

        # 2. Return to initial position (even if stopped, return for safety)
        logger.info(" Returning to initial position after command execution...")
        if not self.return_to_initial_position():
            logger.warning(" Failed to return to initial position.")
        

        return self.execution_stats['failed_commands'] == 0
    

    def run_process(self, process_name: str) -> bool:
        """
        Execute commands for a specific process only.
        

        Args:
            process_name (str): Process name to execute
            

        Returns:
            bool: True if execution succeeded
        """
        if not self.is_initialized:
            logger.error(" System not initialized. Call initialize() first.")
            return False
        

        # 1. Set initial position
        logger.info(" Setting initial position before process execution...")
        if not self.set_initial_position():
            logger.warning(" Initial position setup failed but continuing process execution.")
        

        # Extract commands within the specified process boundaries
        process_commands = []
        in_process = False
        

        for command in self.command_parser.commands:
            if command.get('type') == 'process_start' and command.get('name') == process_name:
                in_process = True
                continue
            elif command.get('type') == 'process_end' and command.get('name') == process_name:
                break
            elif in_process:
                process_commands.append(command)
        

        if not process_commands:
            logger.warning(f" Process '{process_name}' not found")
            return False
        

        logger.info(f" Starting process '{process_name}': {len(process_commands)} commands")
        logger.info("=" * 60)
        

        # Initialize execution statistics
        self.execution_stats['total_commands'] = len(process_commands)
        self.execution_stats['successful_commands'] = 0
        self.execution_stats['failed_commands'] = 0
        self.execution_stats['skipped_commands'] = 0
        

        for i, command in enumerate(process_commands, 1):
            # Check stop state
            if self.is_stopped:
                logger.info(" Execution stopped.")
                break
            

            # Wait while paused
            while self.is_paused and not self.is_stopped:
                time.sleep(0.1)  # Wait 100ms
            

            # Recheck stop state
            if self.is_stopped:
                logger.info(" Stopped while paused.")
                break
            

            logger.info(f" [{i}/{len(process_commands)}] Processing command...")
            

            # Wait for user input
            command_name = command.get('name') or command.get('action', 'Unknown')
            command_type = command.get('type', 'unknown')
            description = command.get('description', '')
            

            print(f"\n{'='*60}")
            print(f" Executing next command:")
            print(f" Type: {command_type}")
            print(f" Name: {command_name}")
            if description:
                print(f" Description: {description}")
            print(f"{'='*60}")
            

            # Wait for user input only in interactive mode
            if self.interactive_mode:
                input("Press Enter to execute the command...")
            

            success = self.command_executor.execute_command(command)
            

            if success:
                self.execution_stats['successful_commands'] += 1
            else:
                self.execution_stats['failed_commands'] += 1
                # On command failure: immediately move to top then return to initial position
                logger.error(f" Starting safe return due to command failure: {command_name}")
                if not self.return_to_initial_position():
                    logger.error(" Safe return failed - manual intervention may be required.")
                # Stop loop after failure
                logger.error(" Stopping process execution due to command failure.")
                break
            

            # Call progress callback
            if self.progress_callback:
                progress_percent = int((i / len(process_commands)) * 100)
                self.progress_callback(progress_percent, i, len(process_commands))
            

            time.sleep(0.5)
        

        self._print_execution_summary()
        

        # 2. Return to initial position
        logger.info(" Returning to initial position after process execution...")
        if not self.return_to_initial_position():
            logger.warning(" Failed to return to initial position.")
        

        return self.execution_stats['failed_commands'] == 0
    

    def _print_execution_summary(self):
        """Print execution result summary."""
        logger.info("=" * 60)
        logger.info(" Execution result summary")
        logger.info(f" Total commands: {self.execution_stats['total_commands']}")
        logger.info(f" Success: {self.execution_stats['successful_commands']} ")
        logger.info(f" Failed: {self.execution_stats['failed_commands']} ")
        logger.info(f" Skipped: {self.execution_stats['skipped_commands']} ")
        

        if self.execution_stats['total_commands'] > 0:
            success_rate = (self.execution_stats['successful_commands'] /
                           self.execution_stats['total_commands']) * 100
        else:
            success_rate = 0.0
        logger.info(f" Success rate: {success_rate:.1f}%")
        logger.info("=" * 60)
    

    def cleanup(self):
        """Clean up system and release resources."""
        logger.info(" Cleaning up system...")
        

        if self.interface_manager:
            self.interface_manager.disconnect_all()
        

        logger.info(" System cleanup completed")




def main():
    """
    Main execution function - accepts filename argument and selects execution mode.
    """
    import argparse
    import sys
    

    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Action Commander - Integrated Robot Control System')
    parser.add_argument('json_file', nargs='?', default=None,
                       help='Path to JSON command file (omit to start with empty command list)')
    

    args = parser.parse_args()
    

    print(" Action Commander starting")
    print("=" * 50)
    print(f" JSON file: {args.json_file}")
    print("=" * 50)


    # Configure stdin
    sys.stdin = open('/dev/tty')
    

    # Create Action Commander instance (interactive mode by default)
    commander = ActionCommander(args.json_file, interactive_mode=False)
    

    try:
        # Initialize system
        if not commander.initialize():
            print(" Initialization failed")
            return
        

        # Select execution option
        print("\nSelect execution option:")
        print("1. Execute all commands (interactive)")
        print("2. Execute all commands (automatic)")
        print("3. Exit")
        

        choice = input("\nSelect (1-3): ").strip()
        

        if choice == "1":
            print("\n Executing all commands... (interactive mode)")
            commander.interactive_mode = True
            commander.run_all_commands()
        elif choice == "2":
            print("\n Executing all commands... (automatic mode)")
            commander.interactive_mode = False
            commander.run_all_commands()
        elif choice == "3":
            print(" Exiting")
        else:
            print(" Invalid selection")
    

    except KeyboardInterrupt:
        print("\n Interrupted by user")
    except Exception as e:
        print(f" Error occurred: {e}")
    finally:
        # Cleanup
        commander.cleanup()
        print(" Execution completed")




if __name__ == "__main__":
    main()
