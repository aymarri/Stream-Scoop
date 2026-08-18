import os
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

"""The purpose of this file is to just calculate the total number of lines of code in the project, excluding certain files and directories.
It uses the 'rich' library to display the results in a visually appealing way."""#


def count_lines():
    console = Console()
    
   
    ignore_list = ['__pycache__', 'stockfish', 'total_lines.py', '.git']
    
   
    file_data = []
    grand_total = 0
    
  
    files = [f for f in os.listdir('.') if f.endswith('.py') and f not in ignore_list]
    files.sort() 

  
    table = Table(title="📊 Codebase Statistics", box=box.ROUNDED, header_style="bold cyan")
    table.add_column("File Name", style="green")
    table.add_column("Lines of Code", justify="right", style="yellow")

    for file_name in files:
        try:
            with open(file_name, 'r', encoding='utf-8') as f:
                lines = len(f.readlines())
                file_data.append((file_name, lines))
                grand_total += lines
                table.add_row(file_name, str(lines))
        except Exception as e:
            table.add_row(file_name, f"[red]Error: {e}[/red]")

    
    console.print(table)

  
    summary_content = f"Total Python Files: [bold white]{len(files)}[/bold white]\n"
    summary_content += f"Total Lines of Code: [bold green]{grand_total}[/bold green]"
    
    console.print(Panel(summary_content, title="[bold magenta]Summary[/bold magenta]", border_style="magenta", expand=False))

if __name__ == "__main__":
    count_lines()