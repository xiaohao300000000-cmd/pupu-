import typer

app = typer.Typer(
    name="pupu",
    help="Pupu assistant validation and control commands.",
    no_args_is_help=True,
)


@app.command()
def version() -> None:
    """Print the package version."""
    from pupu_assistant import __version__

    typer.echo(__version__)
