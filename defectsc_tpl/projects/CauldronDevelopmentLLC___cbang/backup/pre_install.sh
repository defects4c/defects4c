



if which "scons" &> /dev/null; then
    echo "scons exists"
else
	apt-get update -y  && apt-get install -y scons 
    echo "scons not exists"
fi
