import sys
sys.path.insert(0, "/app")

from app.tasks.bot_activator_task import activate_signal

# ENA signal 4bb32872-a768-4fd4-9ed8-f92ffcc8ff3f
result = activate_signal("4bb32872-a768-4fd4-9ed8-f92ffcc8ff3f")
print("Result:", result)
