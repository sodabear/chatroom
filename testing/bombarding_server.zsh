# oneliner
# works in Zsh (my Arch) and Bash (Kev's Ubuntu)
addr=192.168.11.12; while :; do open_port=$(nmap -p12340-12349 -n $addr | awk '$2 == "open" {print substr($1, 0, index($1, "/")-1)}'); [[ $open_port == 123* ]] || { echo 'Open port not found. will check again soon   ($RANDOM: '$((RANDOM))')'; sleep 1; continue; }; echo "Found TCP port at $open_port, start bombarding";            until ruby -e 'chars="qwertyuiopasdfghjklzxcvbnm,.!@$%^&*(){}[]:;|/?<>~1234567890-=_+ ".chars.to_a; chan=chars[0..9].sample; def pu(msg); $stderr.puts msg; puts msg; end; pu "/create %s"%chan; pu "/join %s"%chan; while rand > 0.1; pu chars.sample(rand(10)).join; end' | ./client.py Bar $addr $open_port | tee /dev/stderr | grep 'Unable to connect to'; do sleep $((0)); done;         echo 'Server seems to be down'; done

# NOTE 用尽可能短的信息，尤其是send nothing和send 1 byte，来测试，最容易触发错误（因为频繁建立和断开连接）
#      发长信息也有用，因为可以在OS buffer里面塞上超过一条信息。










exit

# formatted version (仅供阅读。以oneliner为准)
addr=192.168.11.12
while :; do
    open_port=$(nmap -p12340-12349 -n $addr | awk '$2 == "open" {print substr($1, 0, index($1, "/")-1)}')
    [[ $open_port == 123* ]] || {
        echo 'Open port not found. will check again soon   ($RANDOM: '$((RANDOM))')'
        sleep 1
        continue
    }
    echo "Found TCP port at $open_port, start bombarding"
    until ruby -e 'chars="qwertyuiopasdfghjklzxcvbnm,.!@$%^&*(){}[]:;|/?<>~1234567890-=_+ ".chars.to_a
                   chan=chars[0..9].sample
                   def pu(msg)
                     $stderr.puts msg
                     puts msg
                   end
                   pu "/create %s"%chan
                   pu "/join %s"%chan
                   while rand > 0.1
                     pu chars.sample(rand(10)).join
                   end' \
        | ./client.py Bar $addr $open_port \
        | tee /dev/stderr \
        | grep 'Unable to connect to'
    do sleep $((0)); done
    echo 'Server seems to be down'
done

