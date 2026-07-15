from server.game_server import create_server_state, run_server


server_state = create_server_state(
    match_duration=15,
    shape_interval=0.8,
    shape_lifetime=1.5,
)
run_server(server_state)
