if [ -f ~/.bashrc ]; then
   . ~/.bashrc
fi

if [ -z $DISPLAY ] && [ "${XDG_VTNR:-0}" -eq 1 ]; then
   startx -- -nocursor
fi
