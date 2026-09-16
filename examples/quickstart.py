"""
Simple example of running and viewing multiple shell tasks.
"""

from oxen import Oxen, Shell

(
    Oxen(
        # Add three shell tasks
        Shell('ping google.com'),
        Shell('traceroute google.com'),
        Shell('iostat 1'),
    )
    # Run the added tasks and display the TUI
    .run()
)
