# LG TV integration for Remote Two/3

Using [AioWebOSTV](https://github.com/home-assistant-libs/aiowebostv)
and [uc-integration-api](https://github.com/aitatoi/integration-python-library)

The driver discovers LG TVs on the network. A media player, a remote entity and several sensors entities are exposed to the core.

Supported attributes:
- State (on, off, playing, paused, unknown)
- Title
- Artwork
- Source


Supported commands:
- Turn on
- Turn off
- Direction pad and enter
- Back
- Next
- Previous
- Volume up
- Volume down
- Pause / Play
- Input select
- Channels Up/Down
- Menus (home, context, settings)
- Colored buttons
- Digit numbers
- Subtitle/audio language switching

4 sensors are exposed :
- Current input source
- Current volume level
- Muted state
- Current sound output

## Installation on the Remote

### Pre-requisites

To make the TV available on the network and be able to power it through the network, some settings have to be enabled in the TV settings, depending on your model.

_About setting up both IP and Mac addresses_ : when the TV is off, it is no longer accessible through its IP address (even though it remains connected a few minutes after power-off).
<br>The only way to turn on the TV is to send a `magic packet` to its mac address.


Therefore the following settings have to be enabled, and then the mac address correclty set-up in the setup flow. Also there are 2 mac addresses (wifi and ethernet). You can find the mac address in accessibility settings or network settings if they are not correctly detected by the setup flow (usually models < G2).


Usually the controls to enable are located in `Settings > Support > IP control Settings` for recent models :
- Wake On LAN located in `Settings > Support > IP control Settings` for recent models
- Also enable `Network IP Control` in the same section
- Also enable `SDDP` for automatic device discovery
- LG Connect Apps feature in Network settings or Mobile App in General settings of the TV for older models
- Other settings to check depending on the model range :
  - Enable `Quickstart+` (up to 2021 models)
  - Enable `Always ready` (2022 or later)
  - Disable `HDD Eco Mode`

<img src="https://github.com/user-attachments/assets/19413040-76bf-4003-8a7e-3e09034f7a41" width="350">

If you have troubles connecting to the TV, try to unplug and replug electrically the TV to recover a better network state.

### Setup

- Download the release from the release section : file ending with `.tar.gz`, do not unzip it
- Navigate into the Web Configurator of the remote, go into the `Integrations` tab, click on `Add new` and select : `Install custom`
- Select the downloaded `.tar.gz` file and click on upload
- Once uploaded, the new integration should appear in the list : click on it and select `Start setup`
- Your TV must be running and connected to the network before proceeding (a pairing prompt will be displayed)
- The setup will be able to discover the LG TVs if they are connected on the same network, otherwise it is necessary to set manual IP
- At the end, most users should enable the `Media Player` entity. `Remote entity` is useful for custom commands and commands sequence


### Upgrade and backup/restore

The remote doesn't allow to upgrade an existing integration yet : it is necessary to remove the existing integration (twice) before being able to install a new release.<br>
However the integration lets backup or restore the devices configuration (in JSON format), so that you don't have to perform the setup and pairing process again.

If you want to upgrade the integration to a new release, or simply wants to backup the configuration for later restore or cloning the configuration to another remote, you can use backup/restore.

To use this functionality, launch the setup flow of your existing integration, and select the `Backup or restore` option in the setup flow :
<img width="350" alt="image" src="https://github.com/user-attachments/assets/28799000-d6c9-4f99-86b1-286a857d12bb" />

Then you will have a text field with the current configuration. This field which will be empty if no devices are configured. 
Then just save the content of the text field in a file for later restore and abort the setup flow (clicking next will apply this configuration)

You can now remove the integration and upload the new one. Once you launch the setup flow, you will have an option to perform the normal setup flow or restore a configuration.
Select this option and just replace the content of the text field by the previously saved configuration and click on next to apply it. 
<br>
Beware while using this functionality : the expected format should be respected and could change in the future.
If the format is not recognized, the import will be aborted and existing configuration will remain unchanged.

This functionnality can also be used to clone a configuration from one remote to another.


## Configuration

### Wake on lan

When the TV is off, it is not connected to the network (no IP available) : it can only be turned on while sending a "magic packet" also called WoL (wake on lan), which is a network packet broadcasted to the mac address of the TV.
This is the reason why the network settings above have to be correctly set to enable "wake on lan" from the TV, as well as setting up the correct Mac Addresses in the integration.
As there are 2 mac addresses - one for wifi, one for wired connection - both should be filled in : the integration will systematically send 2 magic packets to both macs.
Please note that when you power off the TV, its connection (and IP) remains active during ~15 minutes : so you have to wait more than 15 minutes to test power on lan.
Also depending on your router, even if the mac addresses are correct it may not work with the default settings
So in the setup flow there is a specific section to set and test the wake on lan :
- Interface : should be set to "0.0.0.0" which means all interfaces if setting up the integration on the remote
- Broadcast : should be empty by default (which means broadcast to all network 255.255.255.255) but some routers won't allow this. If wake on lan fails, try to set your subnet mask. For example if your network is `192.168.1.*` => set `192.168.1.255`
- Wake on lan port : should not be modified, leave to 9
- Tick `Test turn on your configured TV` to test that wol is working (after powering off your TV for at least 15 minutes)

<img width="350" alt="image" src="https://github.com/user-attachments/assets/ef95a3d3-0b62-4f84-b180-7bb6bfd8d70b" />
<img width="350" alt="image" src="https://github.com/user-attachments/assets/4cb4357c-f2b7-4ace-b349-d416246c0511" />


### Available commands

After setting up the integration, you should add and use the `Media Player` entity, which should suit all needs with all its predefined commands.
For custom commands, or to create commands sequence you can also use the `Remote` entity.

### Simple commands

Simple commands are additional commands that are available on both `Media Player` and `Remote` entities.

| Simple command   | Description                        |
|------------------|------------------------------------|
| ASTERISK         | *                                  |
| 3D_MODE          | 3D mode                            |
| AD               | Toggle audio description           |
| AMAZON           | Amazon                             |
| ASPECT_RATIO     | Quick Settings Menu - Aspect Ratio |
| CC               | Closed Captions                    |
| DASH             | Live TV                            |
| EXIT             | Exit                               |
| GUIDE            | Guide                              |
| INPUT_HUB        | Home Dashboard                     |
| LIST             | Live TV                            |
| LIVE_ZOOM        | Live Zoom                          |
| MAGNIFIER_ZOOM   | Focus Zoom                         |
| MYAPPS           | Home Dashboard                     |
| NETFLIX          | Netflix                            |
| PAUSE            | Pause                              |
| PLAY             | Play                               |
| POWER            | Power button                       |
| PROGRAM          | TV Guide                           |
| RECENT           | Home Dashboard - Recent Apps       |
| SAP              | Multi Audio Setting                |
| SCREEN_REMOTE    | Screen Remote                      |
| TELETEXT         | Teletext                           |
| TEXTOPTION       | Text option                        |
| INPUT_SOURCE     | Next input source                  |
| TURN_SCREEN_ON   | Turn screen On                     |
| TURN_SCREEN_OFF  | Turn screen Off                    |
| TURN_SCREEN_ON4  | Turn screen On WebOS <=4           |
| TURN_SCREEN_OFF4 | Turn screen Off WebOS <=4          |

### Remote entity commands

In addition of simple commands above, the remote entity `Send command` and `Commands sequence` support custom commands as well as all the commands exposed by the `Media Player` entity.

Here are the available commmands :

| Command           | Description                                                                               |
|-------------------|-------------------------------------------------------------------------------------------|
| _Custom commands_ | See [this chapter](#remote-entity-commands--custom-commands) with the list and parameters |
| LEFT              | Pad left                                                                                  |
| RIGHT             | Pad right                                                                                 |
| UP                | Pad Up                                                                                    |
| DOWN              | Pad down                                                                                  |
| RED               | Red function                                                                              |
| GREEN             | Green function                                                                            |
| YELLOW            | Yellow function                                                                           |
| BLUE              | Blue function                                                                             |
| CHANNELUP         | Channel Up                                                                                |
| CHANNELDOWN       | Channel Down                                                                              |
| VOLUMEUP          | Volume Up                                                                                 |
| VOLUMEDOWN        | Volume Down                                                                               |
| PLAY              | Play                                                                                      |
| PAUSE             | Pause                                                                                     |
| STOP              | Stop                                                                                      |
| REWIND            | Rewind                                                                                    |
| FASTFORWARD       | Fast forward                                                                              |
| ASTERISK          | *                                                                                         |
| BACK              | Back                                                                                      |
| EXIT              | Exit                                                                                      |
| ENTER             | Enter                                                                                     |
| AMAZON            | Amazon                                                                                    |
| NETFLIX           | NETFLIX                                                                                   |
| 3D_MODE           | 3D mode                                                                                   |
| AD                | Audio description                                                                         |
| ASPECT_RATIO      | Quick Settings Menu - Aspect Ratio                                                        |
| CC                | Closed Captions                                                                           |
| DASH              | Live TV                                                                                   |
| GUIDE             | Guide                                                                                     |
| HOME              | Home Dashboard                                                                            |
| INFO              | Info button                                                                               |
| INPUT_HUB         | Home Dashboard                                                                            |
| LIST              | Live TV                                                                                   |
| LIVE_ZOOM         | Live Zoom                                                                                 |
| MAGNIFIER_ZOOM    | Focus Zoom                                                                                |
| MENU              | Quick Settings Menu                                                                       |
| MUTE              | Myte                                                                                      |
| MYAPPS            | Home Dashboard                                                                            |
| POWER             | Power button                                                                              |
| PROGRAM           | TV Guide                                                                                  |
| QMENU             | Quick Settings Men                                                                        |
| RECENT            | Home Dashboard - Recent Apps                                                              |
| RECORD            | Record                                                                                    |
| SAP               | Multi Audio Setting                                                                       |
| SCREEN_REMOTE     | Screen Remote                                                                             |
| TELETEXT          | Teletext                                                                                  |
| TEXTOPTION        | Text option                                                                               |
| 0                 | 0                                                                                         |
| 1                 | 1                                                                                         |
| 2                 | 2                                                                                         |
| 3                 | 3                                                                                         |
| 4                 | 4                                                                                         |
| 5                 | 5                                                                                         |
| 6                 | 6                                                                                         |
| 7                 | 7                                                                                         |
| 8                 | 8                                                                                         |
| 9                 | 9                                                                                         |


### Remote entity commands : custom commands

With the `Remote` entity one can call commands with parameters.

<img width="323" height="330" alt="image" src="https://github.com/user-attachments/assets/793b0df6-1869-41a2-971b-f0d2ccaf36f3" />


_There are 2 types of commands because some need to go through the internal Luna API. There is also a predefined `picture` command for picture settings.
See [this link](https://github.com/chros73/bscpylgtv) for further information about available commands._

Examples of commands : 
<br>_Warning : commands length is limited (64 characters)_

| Command                                                     | Description                                                                              | Example                                  |
|-------------------------------------------------------------|------------------------------------------------------------------------------------------|------------------------------------------|
| channel '123'                                               | Switch to given channel number or name                                                   | channel 'MTV'                            |
| picture contrast `value`                                    | Set contrast<br/>Relative value : use sign (eg +10 or -10)<br/>or absolute value         | picture contrast +10                     |
| picture backlight `value`                                   | Set backlight <br/>Relative value : use sign (eg +10 or -10)<br/>or absolute value       | picture backlight 80                     |
| picture brightness `value`                                  | Set brightness <br/>Relative value : use sign (eg +10 or -10)<br/>or absolute value      | picture brightness -10                   |
| system.launcher/launch `{'id':'com.webos.app.screensaver'}` | Start screensaver                                                                        |                                          |
| system.launcher/close `{'id':'com.webos.app.screensaver'}`  | Stop screensaver                                                                         |                                          |
| luna picture `{'pictureMode':'MODE'}`                       | Set picture mode to given mode                                                           | `luna picture {'pictureMode':'expert2'}` |
| luna picture `{'backlight':0,'contrast':85}`                | Set picture settings once                                                                |                                          |
| luna picture `{'hdrDynamicToneMapping':'on'}`               | Turn hdrDynamicToneMapping on in the current HDR10 picture preset                        |                                          |
| luna other `{'eotf':'hlg'}`                                 | Setting EOTF in HDMI Signal Override menu, values: auto, sdrGamma, hdrGamma, st2084, hlg |                                          |


## Advanced usage

### Setup as external integration

- Requires Python 3.11
- Under a virtual environment : the driver has to be run in host mode and not bridge mode, otherwise the turn on function won't work (a magic packet has to be sent through network and it won't reach it under bridge mode)
- Enable always on on your LG TV to be able to power on lan (see https://www.home-assistant.io/integrations/webostv/)
- When using this integration as external (docker...), set this environment variable to avoid errors : `UC_EXTERNAL`
- Install required libraries:  
  (using a [virtual environment](https://docs.python.org/3/library/venv.html) is highly recommended)

```shell
pip3 install -r requirements.txt
```

For running a separate integration driver on your network for Remote Two/3, the configuration in file
[driver.json](driver.json) needs to be changed:

- Set `driver_id` to a unique value, `lgwebos_driver` is already used for the embedded driver in the firmware.
- Change `name` to easily identify the driver for discovery & setup with Remote Two or the web-configurator.
- Optionally add a `"port": 8090` field for the WebSocket server listening port.
    - Default port: `9090`
    - Also overrideable with environment variable `UC_INTEGRATION_HTTP_PORT`

### Run

```shell
python3 src/driver.py
```

See
available [environment variables](https://github.com/unfoldedcircle/integration-python-library#environment-variables)
in the Python integration library to control certain runtime features like listening interface and configuration
directory.

## Build self-contained binary for Remote Two/3

After some tests, turns out python stuff on embedded is a nightmare. So we're better off creating a single binary file
that has everything in it.

To do that, we need to compile it on the target architecture as `pyinstaller` does not support cross compilation.

### x86-64 Linux

On x86-64 Linux we need Qemu to emulate the aarch64 target platform:

```bash
sudo apt install qemu binfmt-support qemu-user-static
docker run --rm --privileged multiarch/qemu-user-static --reset -p yes
```

Run pyinstaller:

```shell
docker run --rm --name builder \
    --platform=aarch64 \
    --user=$(id -u):$(id -g) \
    -v "$PWD":/workspace \
    docker.io/unfoldedcircle/r2-pyinstaller:3.11.6  \
    bash -c \
      "python -m pip install -r requirements.txt && \
      pyinstaller --clean --onedir --name driver src/driver.py"
```

### aarch64 Linux / Mac

On an aarch64 host platform, the build image can be run directly (and much faster):

```shell
docker run --rm --name builder \
    --user=$(id -u):$(id -g) \
    -v "$PWD":/workspace \
    docker.io/unfoldedcircle/r2-pyinstaller:3.11.6  \
    bash -c \
      "python -m pip install -r requirements.txt && \
      pyinstaller --clean --onedir --name driver src/driver.py"
```

## Versioning

We use [SemVer](http://semver.org/) for versioning. For the versions available, see the
[tags and releases in this repository](https://github.com/albaintor/integration-lgtv/releases).

## Changelog

The major changes found in each new release are listed in the [changelog](CHANGELOG.md)
and under the GitHub [releases](https://github.com/albaintor/integration-lgtv/releases).

## Contributions

Please read our [contribution guidelines](CONTRIBUTING.md) before opening a pull request.

## License

This project is licensed under the [**Mozilla Public License 2.0**](https://choosealicense.com/licenses/mpl-2.0/).
See the [LICENSE](LICENSE) file for details.
