#!/usr/bin/python3
"""
Drawer Motor Diagnostic Tool

Commands:
    home              - Home the drawer (fully retracted)
    open              - Open the drawer (fully extended)
    read              - Move to read position
    steps N           - Move N steps from home (homes first, then moves)
    steps N --no-home - Move N steps from current position (no homing)
    status            - Report current position and config

Examples:
    python3 motor_drawer.py home
    python3 motor_drawer.py open
    python3 motor_drawer.py read
    python3 motor_drawer.py steps 200
    python3 motor_drawer.py steps 50 --no-home
    python3 motor_drawer.py steps -50 --no-home   # Move back toward home
"""

import sys
import argparse
from datetime import datetime

# Try to import hardware libraries - graceful fallback for testing
try:
    import RPi.GPIO as GPIO
    from sentri_lib.motor_class import Drawer
    from sentri_lib.config_module import Config
    HARDWARE_AVAILABLE = True
    
    # Load actual config
    config = Config()
    DRAWER_MAX_STEPS = config.drawer["open_steps"]      # 4500 - max travel
    DRAWER_MIN_STEPS = 0                                 # Home position
    DRAWER_READ_STEPS = config.drawer["read_steps"]     # 151 or 160 depending on device
    DRAWER_HOME_STEPS = config.drawer["home_steps"]     # 5000 - used for homing (overshoots, stops at flag)
    STEP_DELAY = 0.001
    
except ImportError as e:
    print(f"[WARNING] Hardware libraries not available: {e}", file=sys.stderr)
    print("[WARNING] Running in simulation mode", file=sys.stderr)
    HARDWARE_AVAILABLE = False
    
    # Defaults based on config for simulation
    DRAWER_MAX_STEPS = 4500
    DRAWER_MIN_STEPS = 0
    DRAWER_READ_STEPS = 151
    DRAWER_HOME_STEPS = 5000
    STEP_DELAY = 0.001


def log(msg):
    """Print timestamped message to stderr for diagnostics"""
    timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    print(f"[{timestamp}] {msg}", file=sys.stderr)


def create_drawer():
    """Create and return drawer instance"""
    if not HARDWARE_AVAILABLE:
        log("SIMULATION MODE - no actual motor movement")
        return None
    return Drawer()


def cmd_home(drawer):
    """Home the drawer (fully retracted)"""
    log("COMMAND: Home drawer")
    log(f"Sending {DRAWER_HOME_STEPS} steps back, will stop at home flag")
    
    if drawer:
        ret = drawer.home()
        log(f"Home complete. Position: {drawer.position}")
        return ret
    else:
        log("[SIM] Would home drawer")
        return 0


def cmd_open(drawer):
    """Open the drawer (fully extended)"""
    log("COMMAND: Open drawer")
    log(f"Target: {DRAWER_MAX_STEPS} steps (fully open)")
    
    if drawer:
        ret = drawer.open()
        log(f"Open complete. Position: {drawer.position}")
        return ret
    else:
        log(f"[SIM] Would open drawer to {DRAWER_MAX_STEPS} steps")
        return 0


def cmd_read(drawer):
    """Move to read position"""
    log(f"COMMAND: Move to read position ({DRAWER_READ_STEPS} steps from home)")
    
    if drawer:
        ret = drawer.read()
        log(f"Read position reached. Position: {drawer.position}")
        return ret
    else:
        log(f"[SIM] Would home then move {DRAWER_READ_STEPS} steps")
        return 0


def cmd_steps(drawer, steps, from_home=True, current_position=0):
    """
    Move specified number of steps.
    
    Args:
        drawer: Drawer instance
        steps: Number of steps to move (positive = out/away from home, negative = back/toward home)
        from_home: If True, home first then move. If False, move from current position.
        current_position: Estimated current position (for safety checks when not homing)
    """
    if from_home:
        log(f"COMMAND: Move {steps} steps from home")
        
        # Safety check - after homing, we're at 0, so target is just `steps`
        target_position = steps
        
        if target_position < DRAWER_MIN_STEPS:
            log(f"ERROR: Target position ({target_position}) below minimum ({DRAWER_MIN_STEPS})")
            return -1
        if target_position > DRAWER_MAX_STEPS:
            log(f"ERROR: Target position ({target_position}) exceeds maximum ({DRAWER_MAX_STEPS})")
            return -1
        
        if drawer:
            log("Homing first...")
            drawer.home()
            log(f"Home complete. Position: {drawer.position}")
            
            log(f"Moving {steps} steps out...")
            ret = drawer.move_wo_home_flag(steps, STEP_DELAY)
            log(f"Movement complete. Position: {drawer.position}")
            return ret
        else:
            log(f"[SIM] Would home then move {steps} steps")
            return 0
    else:
        log(f"COMMAND: Move {steps} steps from current position (NO HOME)")
        
        # Get current position from motor if available
        if drawer:
            current_position = drawer.position
        log(f"Current position: {current_position}")
        
        # Calculate target position
        target_position = current_position + steps
        
        # Safety checks
        if target_position < DRAWER_MIN_STEPS:
            log(f"ERROR: Movement would go below minimum ({DRAWER_MIN_STEPS})")
            log(f"       Current: {current_position}, Requested: {steps}, Would be: {target_position}")
            log(f"       Maximum negative steps from here: {-(current_position - DRAWER_MIN_STEPS)}")
            return -1
        if target_position > DRAWER_MAX_STEPS:
            log(f"ERROR: Movement would exceed maximum ({DRAWER_MAX_STEPS})")
            log(f"       Current: {current_position}, Requested: {steps}, Would be: {target_position}")
            log(f"       Maximum positive steps from here: {DRAWER_MAX_STEPS - current_position}")
            return -1
        
        if drawer:
            log(f"Moving {steps} steps {'out' if steps > 0 else 'back'}...")
            ret = drawer.move_wo_home_flag(steps, STEP_DELAY)
            log(f"Movement complete. Position: {drawer.position}")
            return ret
        else:
            log(f"[SIM] Would move {steps} steps (no home)")
            return 0


def cmd_status(drawer):
    """Show current configuration and limits"""
    log("DRAWER CONFIGURATION:")
    log("")
    log(f"  Limits:")
    log(f"    Min (home):     {DRAWER_MIN_STEPS} steps")
    log(f"    Max (open):     {DRAWER_MAX_STEPS} steps")
    log(f"    Home overshoot: {DRAWER_HOME_STEPS} steps (stops at flag)")
    log("")
    log(f"  Preset Positions:")
    log(f"    Home:  {DRAWER_MIN_STEPS} steps")
    log(f"    Read:  {DRAWER_READ_STEPS} steps")
    log(f"    Open:  {DRAWER_MAX_STEPS} steps")
    log("")
    log(f"  Step delay: {STEP_DELAY}s")
    log("")
    if drawer:
        log(f"  Current tracked position: {drawer.position} steps")
        log(f"  Home flag state: {'HOME' if drawer.isHome() else 'NOT HOME'}")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Drawer Motor Diagnostic Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Direction:
    Positive steps = OUT (away from home, toward open)
    Negative steps = BACK (toward home)

Safety Limits (from config):
    Minimum: {min_steps} steps (home)
    Maximum: {max_steps} steps (open)

Examples:
    %(prog)s home                       # Home the drawer
    %(prog)s open                       # Fully open the drawer  
    %(prog)s read                       # Move to read position ({read_steps} steps)
    %(prog)s steps 200                  # Home, then move 200 steps out
    %(prog)s steps 50 --no-home         # Move 50 steps out from current position
    %(prog)s steps -50 --no-home        # Move 50 steps back toward home
    %(prog)s status                     # Show config and current position
        """.format(min_steps=DRAWER_MIN_STEPS, max_steps=DRAWER_MAX_STEPS, read_steps=DRAWER_READ_STEPS)
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # Home command
    subparsers.add_parser('home', help='Home the drawer (fully retracted)')
    
    # Open command
    subparsers.add_parser('open', help='Open the drawer (fully extended)')
    
    # Read command
    subparsers.add_parser('read', help='Move to read position')
    
    # Steps command
    steps_parser = subparsers.add_parser('steps', help='Move specified number of steps')
    steps_parser.add_argument('num_steps', type=int, 
                              help='Steps to move (positive=out, negative=back)')
    steps_parser.add_argument('--no-home', action='store_true', 
                              help='Move from current position instead of homing first')
    
    # Status command
    subparsers.add_parser('status', help='Show configuration and current position')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    # Print header
    log("=" * 60)
    log("DRAWER MOTOR DIAGNOSTIC TOOL")
    log("=" * 60)
    log(f"Hardware available: {HARDWARE_AVAILABLE}")
    log(f"Limits: {DRAWER_MIN_STEPS} (home) to {DRAWER_MAX_STEPS} (open)")
    log(f"Read position: {DRAWER_READ_STEPS} steps")
    log("")
    
    # Create hardware instance
    drawer = create_drawer()
    
    try:
        if args.command == 'home':
            ret = cmd_home(drawer)
        elif args.command == 'open':
            ret = cmd_open(drawer)
        elif args.command == 'read':
            ret = cmd_read(drawer)
        elif args.command == 'steps':
            ret = cmd_steps(drawer, args.num_steps, from_home=not args.no_home)
        elif args.command == 'status':
            ret = cmd_status(drawer)
        else:
            parser.print_help()
            ret = 1
            
    finally:
        # Clean up
        if drawer:
            log("Disabling motor driver...")
            drawer.disable()
            log("Motor disabled.")
    
    log("")
    log("=" * 60)
    log("COMPLETE")
    log("=" * 60)
    
    return ret


if __name__ == "__main__":
    sys.exit(main() or 0)
