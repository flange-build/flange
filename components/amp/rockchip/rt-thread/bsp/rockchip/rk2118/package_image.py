#!/usr/bin/env python3

import sys
import os
import subprocess
import json
import re

xip = False
fw_magic_size = 0x800
unsecure_xip_base = 0x11000000
unsecure_xip_end = 0x20000000
unsecure_ddr_base = 0xa0000000
ddr_addr_gap = 0x40000000
other_addr_gap = 0x10000000
xip_flag_magic = 0x55aaaa55

def get_vectors_section_address(elf_file):
    try:
        # 使用readelf命令获取ELF文件的section信息
        output = subprocess.check_output(['readelf', '-S', elf_file], universal_newlines=True)

        # 解析readelf命令的输出
        for line in output.split('\n'):
            if '.vectors' in line:
                # 提取.vectors section的起始地址
                address = line.split()[4]
                return int(address, 16)

        return None
    except FileNotFoundError:
        print(f"{elf_file} not found")
        return None
    except subprocess.CalledProcessError as e:
        print(f"readelf error: {e}")
        return None

def check_rt_using_xip(elf_file):
    try:
        # 使用readelf命令获取ELF文件的section信息
        output = subprocess.check_output(['readelf', '-S', elf_file], universal_newlines=True)

        # 解析readelf命令的输出
        for line in output.split('\n'):
            if '.xip_flag' in line:
                elements = line.split()
                # 提取.xip_flag section的偏移位置
                address = elements[elements.index('.xip_flag') + 3]
                offset = int(address, 16)
                # 从elf_file偏移位置读取xip_flag的值，并判断是否等于xip_flag_magic
                with open(elf_file, "rb") as bin_file:
                    bin_file.seek(offset)
                    data = bin_file.read(4)
                    if len(data) < 4:
                        print(f"{elf_file} is too small {offset}")
                        return False
            
                    value = int.from_bytes(data, byteorder="little")
                    print(f"xip_flag@{offset:08X}: 0x{value:08X}")
                    return value == xip_flag_magic

        return False
    except FileNotFoundError:
        print(f"{elf_file} not found")
        return False
    except Exception as e:
        print(f"readelf error: {e}")
        return False

# 查找setting.ini中的分区偏移
def find_part_offset(file_path, search_string):
    with open(file_path, 'r') as file:
        lines = file.readlines()

        for i in range(len(lines)):
            if search_string in lines[i]:
                offset_line = lines[i-3]
                if offset_line.startswith('PartOffset='):
                    offset_value = offset_line.split('=')[1].strip()
                    return offset_value

    return None

# 查找parameter中的分区偏移
def find_part_offset_parameter(file_path, search_string):
    pattern = re.compile(r'(0x[0-9a-fA-F]+)@(0x[0-9a-fA-F]+)\s*\({}\)'.format(re.escape(search_string)))

    offset = None
    with open(file_path, 'r') as file:
        for line in file:
            match = pattern.search(line)
            if match:
                offset = match.group(2).strip()
                #print(f"{file_path} {search_string} part offset: {offset}")
                break

    return offset

# 替换打包配置文件中的LOADING_ADDRESS
def replace_loading_address(file_path, new_address, xip_flag):
    try:
        with open(file_path, 'r') as file:
            data = json.load(file)

        # 只有ddr的安全和非安全地址gap是0x40000000, 其他地址空间的gap是0x10000000
        if new_address < unsecure_ddr_base:
            new_address -= other_addr_gap
        else:
            new_address -= ddr_addr_gap
        data['LOADING_ADDRESS'] = f"0x{int(new_address):08X}"

        with open(file_path, 'w') as file:
            json.dump(data, file, indent=4)
            file.write('\n')

        print(f"Replaced LOADING_ADDRESS with 0x{int(new_address):08X} in {file_path}")

    except FileNotFoundError:
        print(f"File {file_path} not found.")
    except json.JSONDecodeError:
        print(f"Error decoding JSON from file {file_path}.")
    except Exception as e:
        print(f"An error occurred: {e}")

# 检查xip地址和分区表中的地址是否一致
def check_xip_addr(setting_file) :
    if ".ini" in setting_file:
        search_list = ['File=../../Image/rtt0.img', 'File=../../Image/rtt0_b.img', 'File=../../Image/rtt1.img', 'File=../../Image/recovery.img']
    else:
        parameter_file = setting_file.replace("package-file", "parameter.txt")
        search_list = ['cpu0_os_a', 'cpu1_os_a', 'recovery']
        img_list = ['rtt0.img', 'rtt1.img', 'recovery.img']

    for index, search_string in enumerate(search_list) :
        # 查找并打印PartOffset，如果没找到就找下一个
        if ".ini" in setting_file:
            part_offset = find_part_offset(setting_file, search_string)
        else:
            part_offset = find_part_offset_parameter(parameter_file, search_string)
        if part_offset is None :
            print(f"not found PartOffset for {search_string}, skipping")
            continue

        # part_offset换算成非安全的xip地址
        part_offset = 512 * int(part_offset, 16)
        part_offset += unsecure_xip_base + fw_magic_size
        print(f"found {search_string} PartOffset: 0x{part_offset:x}")

        # 获得elf文件路径
        if ".ini" in setting_file :
            elf_file = search_string.split('/')[3].strip().replace('.img', '.elf')
            json_file = search_string.split('/')[3].strip().replace('.img', '.json')
        else:
            elf_file = img_list[index].replace('.img', '.elf')
            json_file = img_list[index].replace('.img', '.json')

        if os.path.exists(elf_file) :
            vectors_address = get_vectors_section_address(elf_file)
            if vectors_address is None:
                print(f"can not found .vectors section in {elf_file}")
                continue

            # 分区表得到的part_offset已经被换算成非安全地址，recovery跑在sram安全地址空间，需要换算成非安全地址空间
            if elf_file == "recovery.elf":
                vectors_address += other_addr_gap
            
            # 检查xip flash是否启用，一旦启用，则TFM&CPU1 loader打包的时候都选XIP版本
            if check_rt_using_xip(elf_file):
                global xip
                xip = True
            print(f"CPU_RUN_IN_XIP = {xip}")

            # 获取.vectors section的起始地址，如果不在XIP范围内，则忽略
            if vectors_address < unsecure_xip_base or vectors_address >= unsecure_xip_end :
                print("vectors address is not in the XIP range, check ignore")
                if elf_file == "rtt0.elf" or elf_file == "rtt1.elf" or elf_file == "recovery.elf" :
                    replace_loading_address(f"Image/config/{json_file}", vectors_address, False)
                continue

            if part_offset == vectors_address :
                print(f"{elf_file} part_offset==vectors_address")
            else:
                print(f"Error: {elf_file} part_offset=0x{part_offset:x}, xip_address=0x{vectors_address:x}")

            replace_loading_address(f"Image/config/{json_file}", vectors_address, True)

def adjust_path(path):
    parts = path.split('/')
    if parts[0] == '..' and parts[1] == '..':
        new_path = '/'.join(parts[2:])
        return f"{new_path}"
    return path

def extract_dsp_paths(package_file):
    dsp0_dir = None
    dsp1_dir = None
    dsp2_dir = None

    with open(package_file, 'r') as file:
        for line in file:
            if 'dsp0.bin' in line and dsp0_dir is None:
                dsp0_dir = adjust_path(line.split()[1].strip())
            elif 'dsp1.bin' in line and dsp1_dir is None:
                dsp1_dir = adjust_path(line.split()[1].strip())
            elif 'dsp2.bin' in line and dsp2_dir is None:
                dsp2_dir = adjust_path(line.split()[1].strip())

            if dsp0_dir and dsp1_dir and dsp2_dir:
                break

    return dsp0_dir, dsp1_dir, dsp2_dir

def check_string_in_file(setting_file, target_string):
    try:
        with open(setting_file, "r") as file:
            return target_string in file.read()
    except FileNotFoundError:
        print(f"File '{setting_file}' not found")
    except Exception as e:
        print(f"Error: {e}")
    return False

def package_dsp_fw(package_file):
    base_path = "/".join(setting_file.split("/")[:-1])
    package_file = f"{base_path}/package-file"

    if check_string_in_file(package_file, "#disable_dsp_signature"):
        return;

    dsp0_dir, dsp1_dir, dsp2_dir = extract_dsp_paths(package_file)

    if os.path.exists("./Image/dsp0.img"):
        subprocess.call((f"rm ./Image/dsp0.img"), shell=True)
    if os.path.exists("./Image/dsp1.img"):
        subprocess.call((f"rm ./Image/dsp1.img"), shell=True)
    if os.path.exists("./Image/dsp2.img"):
        subprocess.call((f"rm ./Image/dsp2.img"), shell=True)

    if os.path.exists(dsp0_dir):
        print(f"cp {dsp0_dir} ./Image/dsp0.img")
        subprocess.call((f"cp {dsp0_dir} ./Image/dsp0.img"), shell=True)
        subprocess.call((f"../tools/resource_header_tool pack --json Image/config/dsp.json ./Image/dsp0.img"), shell=True)
    else:
        print(f"Error: cat found {dsp0_dir}")

    if os.path.exists(dsp1_dir):
        print(f"cp {dsp1_dir} ./Image/dsp0.img")
        subprocess.call((f"cp {dsp1_dir} ./Image/dsp1.img"), shell=True)
        subprocess.call((f"../tools/resource_header_tool pack --json Image/config/dsp.json ./Image/dsp1.img"), shell=True)
    else:
        print(f"Error: cat found {dsp1_dir}")

    if os.path.exists(dsp2_dir):
        print(f"cp {dsp2_dir} ./Image/dsp0.img")
        subprocess.call((f"cp {dsp2_dir} ./Image/dsp2.img"), shell=True)
        subprocess.call((f"../tools/resource_header_tool pack --json Image/config/dsp.json ./Image/dsp2.img"), shell=True)
    else:
        print(f"Error: cat found {dsp2_dir}")

def package_fw(setting_file):
    # 在xip flash启用的情况下，tfm和cpu1 loader都选用xip模式，车载产品也不需要这些保持活的，所以不影响无感升级
    if xip :
        print(f"cp ./rkbin/tfm_s.bin ./Image/tfm_s.img")
        subprocess.call((f"cp ./rkbin/tfm_s.bin ./Image/tfm_s.img"), shell=True)
        subprocess.call((f"./align_bin_size.sh ./Image/tfm_s.img"), shell=True)
        subprocess.call(("../tools/resource_header_tool pack --json Image/config/tfm_s.json ./Image/tfm_s.img"), shell=True)
        if os.path.exists("./rkbin/tfm_s_mini_a.bin"):
            print(f"cp ./rkbin/tfm_s_mini_a.bin ./Image/tfm_s_mini_a.img")
            subprocess.call((f"cp ./rkbin/tfm_s_mini_a.bin ./Image/tfm_s_mini_a.img"), shell=True)
            subprocess.call((f"./align_bin_size.sh ./Image/tfm_s_mini_a.img"), shell=True)
            subprocess.call(("../tools/resource_header_tool pack --json Image/config/tfm_s_mini_a.json ./Image/tfm_s_mini_a.img"), shell=True)
        if os.path.exists("./rkbin/tfm_s_mini_b.bin"):
            print(f"cp ./rkbin/tfm_s_mini_b.bin ./Image/tfm_s_mini_b.img")
            subprocess.call((f"cp ./rkbin/tfm_s_mini_b.bin ./Image/tfm_s_mini_b.img"), shell=True)
            subprocess.call((f"./align_bin_size.sh ./Image/tfm_s_mini_b.img"), shell=True)
            subprocess.call(("../tools/resource_header_tool pack --json Image/config/tfm_s_mini_b.json ./Image/tfm_s_mini_b.img"), shell=True)
        if os.path.exists("./rkbin/tfm_s_mini.bin"):
            print(f"cp ./rkbin/tfm_s_mini.bin ./Image/tfm_s_mini.img")
            subprocess.call((f"cp ./rkbin/tfm_s_mini.bin ./Image/tfm_s_mini.img"), shell=True)
            subprocess.call((f"./align_bin_size.sh ./Image/tfm_s_mini.img"), shell=True)
            subprocess.call(("../tools/resource_header_tool pack --json Image/config/tfm_s.json ./Image/tfm_s_mini.img"), shell=True)
    else :
        print(f"cp ./rkbin/tfm_s_ddr.bin ./Image/tfm_s.img")
        subprocess.call((f"cp ./rkbin/tfm_s_ddr.bin ./Image/tfm_s.img"), shell=True)
        subprocess.call(("../tools/resource_header_tool pack --json Image/config/tfm_s_ddr.json ./Image/tfm_s.img"), shell=True)

    if xip :
        print(f"cp ./rkbin/cpu1_loader.bin ./Image/cpu1_loader.img")
        subprocess.call((f"cp ./rkbin/cpu1_loader.bin ./Image/cpu1_loader.img"), shell=True)
        subprocess.call((f"./align_bin_size.sh ./Image/cpu1_loader.img"), shell=True)
        subprocess.call(("../tools/resource_header_tool pack --json Image/config/cpu1_loader.json ./Image/cpu1_loader.img"), shell=True)
    else :
        # 在xip flash关掉的情况下，需要跑cpu1，则必须要有ddr
        if os.path.exists("./rkbin/cpu1_loader_ddr.bin"):
            print(f"cp ./rkbin/cpu1_loader_ddr.bin ./Image/cpu1_loader.img")
            subprocess.call((f"cp ./rkbin/cpu1_loader_ddr.bin ./Image/cpu1_loader.img"), shell=True)
            subprocess.call((f"./align_bin_size.sh ./Image/cpu1_loader.img"), shell=True)
            subprocess.call(("../tools/resource_header_tool pack --json Image/config/cpu1_loader_ddr.json ./Image/cpu1_loader.img"), shell=True)

    # rtt和recovery打包
    search_list = ['../../Image/rtt0.img', '../../Image/rtt0_b.img', '../../Image/rtt1.img', '../../Image/recovery.img']
    for search_string in search_list:

        img_file = search_string.split('/')[3].strip()
        bin_file = search_string.split('/')[3].strip().replace('.img', '.bin')
        json_file = search_string.split('/')[3].strip().replace('.img', '.json')

        if not os.path.exists(bin_file):
            print(f"File {bin_file} does not exist, skipping.")
            continue

        subprocess.call((f"cp {bin_file} ./Image/{img_file}"), shell=True)
        subprocess.call((f"../tools/resource_header_tool pack --json Image/config/{json_file} ./Image/{img_file}"), shell=True)

    # 只有parameter.txt有可能打包dsp固件包头，用于签名校验
    if "parameter.txt" in setting_file :
        package_dsp_fw(setting_file)

def update_package_file(setting_file):
    base_path = "/".join(setting_file.split("/")[:-1])
    package_file = f"{base_path}/package-file"

    with open(package_file, 'r') as file:
        lines = file.readlines()

    replacements = {
        "dsp0.bin": "../../Image/dsp0.img",
        "dsp1.bin": "../../Image/dsp1.img",
        "dsp2.bin": "../../Image/dsp2.img"
    }

    with open(package_file, 'w') as file:
        for line in lines:
            for dsp_bin, new_path in replacements.items():
                if dsp_bin in line:
                    line = f"{line.split()[0]}\t{new_path}\n"
            file.write(line)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: " + sys.argv[0] + " <setting.ini or package-file>")
        sys.exit(1)

    setting_file = sys.argv[1]
    if os.path.exists(setting_file) :
        if setting_file.endswith('.ini') :
            check_xip_addr(setting_file)
            package_fw(setting_file)
        else :
            check_xip_addr(setting_file)
            package_fw(setting_file)
            update_package_file(setting_file)
    print("package image finish")
    sys.exit(0)
