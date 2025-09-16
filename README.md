# LG TV integration for Remote Two/3

Using [AioWebOSTV](https://github.com/home-assistant-libs/aiowebostv)
and [uc-integration-api](https://github.com/aitatoi/integration-python-library)

The driver discovers LG TVs on the network. A media player entity is exposed to the core.

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

## Usage

### Installation on the Remote (recommended)

- Enable always on on your LG TV to be able to power on lan (see https://www.home-assistant.io/integrations/webostv/)
- Download the release from the release section : file ending with `.tar.gz`
- Navigate into the Web Configurator of the remote, go into the `Integrations` tab, click on `Add new` and select : `Install custom`
- Select the downloaded `.tar.gz` file and click on upload
- Once uploaded, the new integration should appear in the list : click on it and select `Start setup`
- Your TV must be running and connected to the network before proceed

### Backup or restore configuration

The integration lets backup or restore the devices configuration (in JSON format).
To use this functionality, select the "Backup or restore" option in the setup flow, then you will have a text field which will be empty if no devices are configured. 
- Backup : just save the content of the text field in a file for later restore and abort the setup flow (clicking next will apply this configuration)
- Restore : just replace the content by the previously saved configuration and click on next to apply it. Beware while using this functionality : the expected format should be respected and could change in the future.
If the format is not recognized, the import will be aborted and existing configuration will remain unchanged.


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

Remote entity exposes 3 commands : turn On/Off, power toggle, send a (custom) command and send a command sequence.

Here are the available commmands :
About custom commands `CUSTOM_COMMAND` and `CUSTOM_NOTIFICATION` : these are low level commands that let call any endpoint with parameters : see next chapter

| Command             | Description                                      |
|---------------------|--------------------------------------------------|
| CUSTOM_COMMAND      | Custom command with endpoint and parameters      |
| CUSTOM_NOTIFICATION | Custom Luna command with endpoint and parameters |
| LEFT                | Pad left                                         |
| RIGHT               | Pad right                                        |
| UP                  | Pad Up                                           |
| DOWN                | Pad down                                         |
| RED                 | Red function                                     |
| GREEN               | Green function                                   |
| YELLOW              | Yellow function                                  |
| BLUE                | Blue function                                    |
| CHANNELUP           | Channel Up                                       |
| CHANNELDOWN         | Channel Down                                     |
| VOLUMEUP            | Volume Up                                        |
| VOLUMEDOWN          | Volume Down                                      |
| PLAY                | Play                                             |
| PAUSE               | Pause                                            |
| STOP                | Stop                                             |
| REWIND              | Rewind                                           |
| FASTFORWARD         | Fast forward                                     |
| ASTERISK            | *                                                |
| BACK                | Back                                             |
| EXIT                | Exit                                             |
| ENTER               | Enter                                            |
| AMAZON              | Amazon                                           |
| NETFLIX             | NETFLIX                                          |
| 3D_MODE             | 3D mode                                          |
| AD                  | Audio description                                |
| ASPECT_RATIO        | Quick Settings Menu - Aspect Ratio               |
| CC                  | Closed Captions                                  |
| DASH                | Live TV                                          |
| GUIDE               | Guide                                            |
| HOME                | Home Dashboard                                   |
| INFO                | Info button                                      |
| INPUT_HUB           | Home Dashboard                                   |
| LIST                | Live TV                                          |
| LIVE_ZOOM           | Live Zoom                                        |
| MAGNIFIER_ZOOM      | Focus Zoom                                       |
| MENU                | Quick Settings Menu                              |
| MUTE                | Myte                                             |
| MYAPPS              | Home Dashboard                                   |
| POWER               | Power button                                     |
| PROGRAM             | TV Guide                                         |
| QMENU               | Quick Settings Men                               |
| RECENT              | Home Dashboard - Recent Apps                     |
| RECORD              | Record                                           |
| SAP                 | Multi Audio Setting                              |
| SCREEN_REMOTE       | Screen Remote                                    |
| TELETEXT            | Teletext                                         |
| TEXTOPTION          | Text option                                      |
| 0                   | 0                                                |
| 1                   | 1                                                |
| 2                   | 2                                                |
| 3                   | 3                                                |
| 4                   | 4                                                |
| 5                   | 5                                                |
| 6                   | 6                                                |
| 7                   | 7                                                |
| 8                   | 8                                                |
| 9                   | 9                                                |


### Remote entity commands : custom commands

With `CUSTOM_COMMAND` and `CUSTOM_NOTIFICATION` commands exposed by the `Remote` entity, one can call any endpoint with parameters.

There are 2 types of commands because some need to go through the internal Luna API.
See [this link](https://github.com/chros73/bscpylgtv) for further information about available commands.

Examples of commands : careful when setting up the command in the webconfigurator

#### Using `CUSTOM_COMMAND`

**Screensaver start / stop**

* `CUSTOM_COMMAND system.launcher/launch {'id': 'com.webos.app.screensaver'}`
* `CUSTOM_COMMAND system.launcher/close {'id': 'com.webos.app.screensaver'}`

#### Using `CUSTOM_NOTIFICATION`

**Set picture mode expert2**

`CUSTOM_NOTIFICATION com.webos.settingsservice/setSystemSettings {'category': 'picture', 'settings': {'pictureMode': 'expert2'}}`

**Set picture brightness to 85%**

`CUSTOM_NOTIFICATION com.webos.settingsservice/setSystemSettings {'category': 'picture', 'settings': {'backlight': 0, 'contrast': 85}}`

**Turn hdrDynamicToneMapping on in the current HDR10 picture preset**

`CUSTOM_NOTIFICATION com.webos.settingsservice/setSystemSettings {'category': 'picture', 'settings': {'hdrDynamicToneMapping': 'on'}}`

**Setting EOTF in HDMI Signal Override menu, values: auto, sdrGamma, hdrGamma, st2084, hlg**

`CUSTOM_NOTIFICATION com.webos.settingsservice/setSystemSettings {'category': 'other', 'settings': {'eotf': 'hlg'}}`


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
