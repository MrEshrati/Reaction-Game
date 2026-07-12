import queue
import threading

from shared.threading_tools import claim_shape


shared_shape = {"claimed_by": None}
state_lock = threading.Lock()
start_event = threading.Event()
results = queue.Queue()


# both player threads wait so their clicks begin at nearly the same time
def player_click(player_id):
    start_event.wait()
    claimed_shape = claim_shape(shared_shape, player_id, state_lock)
    results.put((player_id, claimed_shape))


player_one_thread = threading.Thread(target=player_click, args=(1,))
player_two_thread = threading.Thread(target=player_click, args=(2,))

player_one_thread.start()
player_two_thread.start()
start_event.set()

player_one_thread.join()
player_two_thread.join()

while not results.empty():
    player_id, claimed_shape = results.get()
    print(f"Player {player_id} claimed the shape: {claimed_shape}")

print("Server accepted player:", shared_shape["claimed_by"])
