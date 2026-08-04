import os

# Настройки: какие папки и расширения файлов игнорировать
EXCLUDE_DIRS = {'.git', '__pycache__', 'node_modules', '.venv', '.idea', '.vscode', 'dist', 'build'}
TEXT_EXTENSIONS = {'.py', '.js', '.ts', '.c', '.cpp', '.h', '.java', '.go', '.rs', '.php',
                   '.html', '.css', '.md', '.txt', '.json', '.yaml', '.yml', '.sql', '.sh'}
OUTPUT_FILE = 'project_content.txt'


def generate_tree(startpath):
    tree_str = "--- СТРУКТУРА ПРОЕКТА ---\n"
    for root, dirs, files in os.walk(startpath):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        level = root.replace(startpath, '').count(os.sep)
        indent = ' ' * 4 * level
        tree_str += f"{indent}{os.path.basename(root)}/\n"
        sub_indent = ' ' * 4 * (level + 1)
        for f in files:
            tree_str += f"{sub_indent}{f}\n"
    return tree_str


def get_file_content(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"<< Ошибка чтения файла: {e} >>"


def main():
    root_dir = os.getcwd()  # Берет текущую папку, где запущен скрипт

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as out:
        # 1. Записываем структуру
        out.write(generate_tree(root_dir))
        out.write("\n" + "=" * 50 + "\n\n")

        # 2. Обходим файлы и записываем содержимое
        for root, dirs, files in os.walk(root_dir):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

            for file in files:
                if file == OUTPUT_FILE or file == 'repo_to_text.py':
                    continue

                ext = os.path.splitext(file)[1].lower()
                if ext in TEXT_EXTENSIONS:
                    full_path = os.path.join(root, file)
                    relative_path = os.path.relpath(full_path, root_dir)

                    out.write(f"--- FILE START: {relative_path} ---\n")
                    out.write(get_file_content(full_path))
                    out.write(f"\n--- FILE END: {relative_path} ---\n\n")

    print(f"Готово! Весь код собран в файл: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()