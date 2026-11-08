# Surara Control

RGB por tecla, **espaços de tela** (cores da tela refletidas no teclado) e **macros** para o
**Redragon Surara PRO** (USB `0c45:5004`, chip SONiX, protocolo "EVision") no Linux/Wayland (testado no Fedora 44 + KDE Plasma).

## Instalação

```bash
./install.sh        # pacotes, venv, regra udev, atalho no menu e autostart opcional
./surara-control    # abre a interface
```

A regra udev (`packaging/70-surara.rules`) dá ao usuário logado acesso ao canal HID de RGB e aos
eventos de entrada **só deste teclado**. Isso é necessário para as macros, mas também significa que
qualquer programa rodando como seu usuário pode ler o que você digita nele.

## Funções

### Iluminação
- Clique/arraste no desenho para selecionar teclas (Ctrl soma), escolha a cor e “Pintar selecionadas”.
- Efeitos de hardware (onda, respiração, reativo…), brilho (0–4), velocidade, direção.
- **Calibrar LEDs…**: acende um LED por vez; você pressiona (ou clica) a tecla correspondente.
  Faça isso uma vez: o mapa padrão vem do OpenRGB e pode errar teclas ABNT2 (`]`, `\`, `/?`, Enter).

### Espaços de tela
1. “Iniciar captura”: o KDE pergunta quais monitores compartilhar (a permissão fica lembrada).
2. Arraste na prévia para criar um espaço; arraste dentro dele para mover e no canto para redimensionar.
3. Com o espaço selecionado, clique nas teclas que devem receber a cor dele.
4. Marque “Ativar espaços de tela”.

Cálculo da cor (média / mais viva / predominante), suavização, saturação e intensidade são
**globais**: o grupo “Ajustes globais” vale para todos os espaços. Para uma exceção, marque “Usar
ajustes próprios” no espaço (ele aparece com ✎ na lista). “Todos seguem o global” desfaz as exceções.
Pode haver vários espaços, em monitores diferentes, cada um com um conjunto de teclas.

**Grade (▦ Gerar grade…):** divide o monitor em linhas × colunas, ou em uma região por tecla, e liga
cada região às teclas na mesma posição física. O canto superior esquerdo da tela vai para o Esc e o
inferior direito para o Enter do numérico, então o teclado vira um "mini monitor". Dá para usar o
teclado inteiro, só o bloco principal ou as teclas selecionadas, e limitar a uma área do monitor. Os
espaços gerados são normais (editáveis); “Remover grade” apaga só eles.

### Macros
- Gatilho: tecla única ou combinação (Ctrl/Shift/Super valem dos dois lados).
- Modos: executar uma vez, repetir enquanto segurar, liga/desliga, remapear tecla.
- Passos: tecla (tocar/pressionar/soltar), atraso, digitar texto (ABNT2 ou US, com acentos), executar comando, gravar sequência.
- O motor captura o teclado com exclusividade e repassa tudo por um teclado virtual (`uinput`).
- **Emergência:** `Ctrl + Alt + Pause` desliga o motor de macros e devolve o teclado.

### Perfis
A barra no topo da janela salva e carrega perfis. Um perfil guarda cores por tecla, efeito, brilho,
espaços de tela (inclusive a grade) com seus limites, e macros. Ficam fora do perfil e valem para
todos: layout, calibração dos LEDs, permissão de captura, layout do texto e o liga/desliga do motor
de macros. “● alterações não salvas” aparece quando o estado atual difere do perfil salvo. Também dá
para trocar de perfil pela bandeja, importar/exportar `.json` e iniciar com
`surara-control --profile NOME`. Os arquivos ficam em `~/.config/surara-control/profiles/`.

## ⚠️ Memória flash do teclado

Cada escrita de cor leva ~7 ms (uma leitura leva ~1 ms), o que indica que o firmware **grava
as cores na flash** a cada escrita. Os espaços de tela atualizam continuamente, então o programa:

- só reenvia os pacotes (18 LEDs cada) que mudaram;
- espera um intervalo mínimo entre trocas (padrão 2 s) e ignora mudanças de cor menores que o limiar (padrão 48);
- mostra o contador de pacotes escritos.

Para confirmar se as escritas vão mesmo para a flash:

```bash
./surara-control flashtest write   # grava um padrão de teste
# desconecte e reconecte o cabo USB
./surara-control flashtest check   # diz se o padrão sobreviveu e restaura suas cores
```

Se o padrão **não** sobreviver, as escritas ficam só na RAM e você pode diminuir o intervalo entre trocas sem medo de desgaste.

### Por que não tem fade suave nos espaços de tela?

O teclado inteiro **pisca a cada escrita de cor**, mesmo que a cor não mude e mesmo que só um bloco
de teclas seja gravado: o firmware para os LEDs enquanto grava. Testei o comando de "cores dinâmicas"
(`0x12`, o modo direto da versão V2 do protocolo): o teclado responde, mas ignora o comando. Os efeitos
nativos (onda, respiração) ficam lisos porque rodam dentro do firmware. Um fade feito pelo programa
seria uma sequência de escritas, ou seja, uma sequência de piscadas. Por isso a troca é direta e
espaçada: ajuste “Intervalo mínimo entre trocas” e “Mudança mínima de cor” na aba Espaços de tela.

## Linha de comando

```
surara-control                 interface gráfica
surara-control --minimized     direto na bandeja
surara-control daemon          sem interface (macros + espaços + cores)
surara-control apply           aplica cores/efeito salvos e sai
surara-control --profile NOME  carrega um perfil ao iniciar (com gui, daemon ou apply)
```

A configuração fica em `~/.config/surara-control/config.json`. Não rode a interface e o `daemon` ao mesmo tempo.

## Estrutura

| Arquivo | Função |
|---|---|
| `surara/hid.py` | protocolo EVision via `/dev/hidraw` |
| `surara/keymap.py` | layout físico (ABNT2/ANSI) e índices de LED |
| `surara/lighting.py` | composição de cores e envio com limite de taxa |
| `surara/capture.py` | portal ScreenCast + PipeWire/GStreamer |
| `surara/ambient.py` | cálculo de cor dos espaços |
| `surara/macros.py` | grab evdev + uinput, gatilhos e execução |
| `surara/textmap.py` | texto → teclas (ABNT2/US) |
| `surara/gui/` | interface PySide6 |

Protocolo baseado na engenharia reversa do [OpenRGB](https://gitlab.com/CalcProgrammer1/OpenRGB) (`EVisionKeyboardController`).
