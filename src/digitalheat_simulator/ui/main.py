"""Minimal M0 application shell."""

from nicegui import ui


def page() -> None:
    ui.label("DigitalHeat Simulator")
    ui.label("Project foundation — simulation is not yet implemented.")


def main() -> None:
    ui.run(root=page, title="DigitalHeat Simulator", reload=False, show=False)


if __name__ in {"__main__", "__mp_main__"}:
    main()
