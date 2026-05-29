cd ~/sdr_analyzer

# Ejecutar gdb con logging automático
gdb python3 -ex "set logging file gdb_output.txt" \
           -ex "set logging on" \
           -ex "run main.py" \
           -ex "thread apply all bt full" \
           -ex "quit"