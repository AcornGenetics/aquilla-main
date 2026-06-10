#!/usr/bin/python3
"""
Axis Motor Diagnostic Tool

The axis motor positions the optics over the wells. There are 6 positions:
- Positions 0-3: ROX filter over wells 1-4
- Positions 2-5: FAM filter over wells 1-4
- Positions 2 and 3 overlap between ROX and FAM

Positions are calculated as: well_one + (well_spacing * index)
  - well_one: 300 steps (first position)
  - well_spacing: 359 steps (distance between positions)
  - Positions: [300, 659, 1018, 1377, 1736, 2095]

Commands:
    home                  - Home the axis
    pos N                 - Move to position index N (0-5)
    well N --dye fam/rox  - Move specific dye filter over well N (1-4)
    steps N               - Move to N steps from home (homes first)
    steps N --no-home     - Move N steps from current position
    status                - Show well positions and limits

Examples:
    python3 motor_axis.py home
    python3 motor_axis.py pos 3
    python3 motor_axis.py well 2 --dye fam
    python3 motor_axis.py steps 500
    python3 motor_axis.py steps 100 --no-home
    python3 motor_axis.py steps -100 --no-home  # Move back toward home
"""

import sys
import argparse
from datetime import datetime

# Try to import hardware libraries - graceful fallback for testing
try:
    import RPi.GPIO as GPIO
    from aq_lib.motor_class import Axis
    from aq_lib.config_module import Config
    HARDWARE_AVAILABLE = True
    
    # Load actual config
    config = Config()
    AXIS_POSITIONS = config.axis["positions"]
    AXIS_WELL_ONE = AXIS_POSITIONS[0]
    AXIS_WELL_SPACING = AXIS_POSITIONS[1] - AXIS_POSITIONS[0]
    AXIS_HOME_STEPS = config.axis["home_steps"]       # 2500 - used for homing (overshoots, stops at flag)

    AXIS_MIN_STEPS = 0                                 # Home position
    AXIS_MAX_STEPS = AXIS_POSITIONS[5] + 100          # ~2195 - a bit past last position
    STEP_DELAY = 0.001
    
except ImportError as e:
    print(f"[WARNING] Hardware libraries not available: {e}", file=sys.stderr)
    print("[WARNING] Running in simulation mode", file=sys.stderr)
    HARDWARE_AVAILABLE = False
    
    # Defaults based on config for simulation
    AXIS_WELL_ONE = 300
    AXIS_WELL_SPACING = 359
    AXIS_HOME_STEPS = 2500
    AXIS_POSITIONS = [AXIS_WELL_ONE + AXIS_WELL_SPACING * i for i in range(6)]
    AXIS_MIN_STEPS = 0
    AXIS_MAX_STEPS = AXIS_POSITIONS[5] + 100  # ~2195
    STEP_DELAY = 0.001


# Well position mapping for dyes
# ROX: positions 0, 1, 2, 3 correspond to wells 1, 2, 3, 4
# FAM: positions 2, 3, 4, 5 correspond to wells 1, 2, 3, 4
DYE_WELL_MAP = {
    'rox': {1: 0, 2: 1, 3: 2, 4: 3},  # ROX well 1-4 -> position 0-3
    'fam': {1: 2, 2: 3, 3: 4, 4: 5},  # FAM well 1-4 -> position 2-5
}


def log(msg):
    """Print timestamped message to stderr for diagnostics"""
    timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    print(f"[{timestamp}] {msg}", file=sys.stderr)


class MockAxis:
    """Mock axis for simulation mode"""
    def __init__(self):
        self.position = 0
        self.positions = AXIS_POSITIONS
    
    def home(self):
        self.position = 0
        return 0
    
    def move_abs_wo_home_flag(self, pos, delay=0):
        self.position = pos
        return 0
    
    def move_wo_home_flag(self, steps, delay=0):
        self.position += steps
        return steps
    
    def isHome(self):
        return self.position == 0
    
    def disable(self):
        pass


def create_axis():
    """Create and return axis instance"""
    if not HARDWARE_AVAILABLE:
        log("SIMULATION MODE - no actual motor movement")
        return MockAxis()
    return Axis()


def cmd_home(axis):
    """Home the axis"""
    log("COMMAND: Home axis")
    log(f"Sending {AXIS_HOME_STEPS} steps back, will stop at home flag")
    
    ret = axis.home()
    log(f"Home complete. Position: {axis.position}")
    return ret


def cmd_position(axis, position_index):
    """Move to a specific position index (0-5)"""
    if position_index < 0 or position_index > 5:
        log(f"ERROR: Position index must be 0-5, got {position_index}")
        return -1
    
    target_steps = AXIS_POSITIONS[position_index]
    log(f"COMMAND: Move to position {position_index}")
    log(f"Target: {target_steps} steps")
    
    log("Homing first...")
    axis.home()
    log(f"Home complete. Position: {axis.position}")
    
    log(f"Moving to position {position_index} ({target_steps} steps)...")
    ret = axis.move_abs_wo_home_flag(target_steps, STEP_DELAY)
    log(f"Movement complete. Position: {axis.position}")
    return ret


def cmd_well_dye(axis, well_number, dye):
    """Move to position for specific dye over specific well"""
    dye = dye.lower()
    if dye not in DYE_WELL_MAP:
        log(f"ERROR: Dye must be 'fam' or 'rox', got '{dye}'")
        return -1
    
    if well_number < 1 or well_number > 4:
        log(f"ERROR: Well number must be 1-4, got {well_number}")
        return -1
    
    position_index = DYE_WELL_MAP[dye][well_number]
    target_steps = AXIS_POSITIONS[position_index]
    
    log(f"COMMAND: Move {dye.upper()} filter over well {well_number}")
    log(f"Mapped to position index {position_index} ({target_steps} steps)")
    
    return cmd_position(axis, position_index)


def cmd_steps(axis, steps, from_home=True):
    """
    Move specified number of steps.
    
    Args:
        axis: Axis instance
        steps: Number of steps to move (positive = away from home, negative = toward home)
        from_home: If True, home first then move to absolute position.
                   If False, move relative to current position.
    """
    if from_home:
        log(f"COMMAND: Move to {steps} steps from home")
        
        # Safety check - target is absolute position after homing
        if steps < AXIS_MIN_STEPS:
            log(f"ERROR: Target ({steps}) below minimum ({AXIS_MIN_STEPS})")
            return -1
        if steps > AXIS_MAX_STEPS:
            log(f"ERROR: Target ({steps}) exceeds maximum ({AXIS_MAX_STEPS})")
            return -1
        
        log("Homing first...")
        axis.home()
        log(f"Home complete. Position: {axis.position}")
        
        log(f"Moving to absolute position {steps}...")
        ret = axis.move_abs_wo_home_flag(steps, STEP_DELAY)
        log(f"Movement complete. Position: {axis.position}")
        return ret
    else:
        current_position = axis.position
        log(f"COMMAND: Move {steps} steps from current position (NO HOME)")
        log(f"Current position: {current_position}")
        
        # Calculate new absolute position
        target_position = current_position + steps
        
        # Safety check
        if target_position < AXIS_MIN_STEPS:
            log(f"ERROR: Movement would go below minimum ({AXIS_MIN_STEPS})")
            log(f"       Current: {current_position}, Requested: {steps}, Would be: {target_position}")
            log(f"       Maximum negative steps from here: {-(current_position - AXIS_MIN_STEPS)}")
            return -1
        if target_position > AXIS_MAX_STEPS:
            log(f"ERROR: Movement would exceed maximum ({AXIS_MAX_STEPS})")
            log(f"       Current: {current_position}, Requested: {steps}, Would be: {target_position}")
            log(f"       Maximum positive steps from here: {AXIS_MAX_STEPS - current_position}")
            return -1
        
        log(f"Moving {steps} steps {'out' if steps > 0 else 'back'}...")
        ret = axis.move_wo_home_flag(steps, STEP_DELAY)
        log(f"Movement complete. Position: {axis.position}")
        return ret


def cmd_status(axis):
    """Show current configuration and limits"""
    log("AXIS CONFIGURATION:")
    log("")
    log(f"  Limits:")
    log(f"    Min (home):     {AXIS_MIN_STEPS} steps")
    log(f"    Max:            {AXIS_MAX_STEPS} steps")
    log(f"    Home overshoot: {AXIS_HOME_STEPS} steps (stops at flag)")
    log("")
    log(f"  Position Calculation:")
    log(f"    well_one:     {AXIS_WELL_ONE} steps")
    log(f"    well_spacing: {AXIS_WELL_SPACING} steps")
    log("")
    log(f"  Well Positions:")
    for i, pos in enumerate(AXIS_POSITIONS):
        rox_well = i + 1 if i <= 3 else None
        fam_well = i - 1 if i >= 2 else None
        labels = []
        if rox_well and rox_well <= 4:
            labels.append(f"ROX Well {rox_well}")
        if fam_well and fam_well >= 1:
            labels.append(f"FAM Well {fam_well}")
        label_str = " / ".join(labels) if labels else ""
        log(f"    Position {i}: {pos:4d} steps  {label_str}")
    log("")
    log(f"  Dye-to-Well Mapping:")
    log(f"    ROX wells 1-4 -> positions {list(DYE_WELL_MAP['rox'].values())}")
    log(f"    FAM wells 1-4 -> positions {list(DYE_WELL_MAP['fam'].values())}")
    log("")
    log(f"  Current tracked position: {axis.position} steps")
    if hasattr(axis, 'isHome'):
        log(f"  Home flag state: {'HOME' if axis.isHome() else 'NOT HOME'}")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Axis Motor Diagnostic Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Direction:
    Positive steps = away from home
    Negative steps = toward home

Well Position Layout:
    Position 0: {p0:4d} steps - ROX Well 1
    Position 1: {p1:4d} steps - ROX Well 2
    Position 2: {p2:4d} steps - ROX Well 3 / FAM Well 1 (overlap)
    Position 3: {p3:4d} steps - ROX Well 4 / FAM Well 2 (overlap)
    Position 4: {p4:4d} steps - FAM Well 3
    Position 5: {p5:4d} steps - FAM Well 4

Examples:
    %(prog)s home                     # Home the axis
    %(prog)s pos 3                    # Move to position index 3
    %(prog)s well 2 --dye fam         # Move FAM filter over well 2
    %(prog)s well 1 --dye rox         # Move ROX filter over well 1
    %(prog)s steps 500                # Home, then move to 500 steps
    %(prog)s steps 100 --no-home      # Move 100 steps from current position
    %(prog)s steps -100 --no-home     # Move 100 steps back toward home
    %(prog)s status                   # Show positions and limits
        """.format(p0=AXIS_POSITIONS[0], p1=AXIS_POSITIONS[1], p2=AXIS_POSITIONS[2],
                   p3=AXIS_POSITIONS[3], p4=AXIS_POSITIONS[4], p5=AXIS_POSITIONS[5])
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # Home command
    subparsers.add_parser('home', help='Home the axis')
    
    # Position command (by index 0-5)
    pos_parser = subparsers.add_parser('pos', help='Move to position index (0-5)')
    pos_parser.add_argument('index', type=int, help='Position index (0-5)')
    
    # Well command (by well number 1-4 with dye)
    well_parser = subparsers.add_parser('well', help='Move dye filter over well')
    well_parser.add_argument('number', type=int, help='Well number (1-4)')
    well_parser.add_argument('--dye', type=str, required=True, choices=['fam', 'rox', 'FAM', 'ROX'],
                             help='Dye filter to position (fam or rox)')
    
    # Steps command
    steps_parser = subparsers.add_parser('steps', help='Move specified number of steps')
    steps_parser.add_argument('num_steps', type=int, 
                              help='Steps to move (positive=out, negative=back)')
    steps_parser.add_argument('--no-home', action='store_true', 
                              help='Move from current position instead of homing first')
    
    # Status command
    subparsers.add_parser('status', help='Show well positions and limits')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    # Print header
    log("=" * 60)
    log("AXIS MOTOR DIAGNOSTIC TOOL")
    log("=" * 60)
    log(f"Hardware available: {HARDWARE_AVAILABLE}")
    log(f"Limits: {AXIS_MIN_STEPS} (home) to {AXIS_MAX_STEPS} (max)")
    log(f"Positions: {AXIS_POSITIONS}")
    log("")
    
    # Create hardware instance
    axis = create_axis()
    
    try:
        if args.command == 'home':
            ret = cmd_home(axis)
        elif args.command == 'pos':
            ret = cmd_position(axis, args.index)
        elif args.command == 'well':
            ret = cmd_well_dye(axis, args.number, args.dye)
        elif args.command == 'steps':
            ret = cmd_steps(axis, args.num_steps, from_home=not args.no_home)
        elif args.command == 'status':
            ret = cmd_status(axis)
        else:
            parser.print_help()
            ret = 1
            
    except Exception as e:
        log(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        ret = -1
    finally:
        # Clean up
        if axis and hasattr(axis, 'disable'):
            log("Disabling motor driver...")
            axis.disable()
            log("Motor disabled.")
    
    log("")
    log("=" * 60)
    log("COMPLETE")
    log("=" * 60)
    
    return ret


if __name__ == "__main__":
    sys.exit(main() or 0)
