"""
Task dashboards using custom split layouts.
"""

from oxen import Oxen, Shell


def main():
    ping = Shell('ping google.com')
    trace = Shell('traceroute google.com')
    iostat = Shell('iostat 1')

    ox = Oxen()
    ox.add_layout(
        [
            (ping, trace),  # Horizontally stacked
            iostat,
        ],  # Vertically stacked
        name='Dashboard',
        default=True,
    )
    ox.run()


if __name__ == '__main__':
    main()
