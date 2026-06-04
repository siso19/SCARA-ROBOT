# Model
Models form the data layer of the MVC Architecture, holding the in-memory representation of the experimental protocol being designed. It notifies the rest of the system of state changes through Qt signals, and has no knowledge of the UI or robot hardware, dealing only with protocol structure.

**protocol_model.py**

Implements the `ProtocolModel` class that manages the entire protocol as a single source-of-truth dictionary. The protocol follows a three-level nested structure of Protocol → Processes → Orders, where each Order contains one of twelve actions (Equip, Eject, Pick, Place, Take, Apply, Mix, Measure, Open, Close, Wait, Dispose) along with its target, amount, and timing information. It provides full CRUD operations at both the Process and Order levels, and automatically converts between internal Source IDs and user-defined Source Descriptions during file load and save.
