import os

def unite_files(directory, output_file):
    with open(output_file, 'w', encoding='utf-8') as outfile:
        for root, dirs, files in os.walk(directory):
            for file in files:
                if file.endswith('.py'):  # Solo archivos Python
                    filepath = os.path.join(root, file)
                    outfile.write(f"\n{'='*20}\n")
                    outfile.write(f"ARCHIVO: {filepath}\n")
                    outfile.write(f"{'='*20}\n\n")
                    with open(filepath, 'r', encoding='utf-8') as infile:
                        outfile.write(infile.read())
                        outfile.write("\n")

unite_files('.', 'proyecto_completo.txt')
