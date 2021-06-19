import time

# demo1


def process_bar(name,percent,total_length=25):
    bar = ''.join(["▮"] * int(percent * total_length)) + ''
    bar = '\r' + '[' + \
        bar.ljust(total_length) + \
        ' {:0>4.1f}%|'.format(percent*100) +'100%,'+name+']'
    print(bar, end='', flush=True)


for i in range(101):
    time.sleep(0.1)
    end_str = '100%'
    process_bar('do what',i/100)
