# Controllers
Controllers form the coordination layer of the MVC Architecture, receiving user actions from the View, performing the corresponding operations on the Model, and ensuring that the View is refreshed whenever the Model state changes. By routing all protocol modifications through Controllers, the Model is preserved as the single source of truth.

**protocol_controller.py**
Implements the `ProtocolController` class that mediates between the protocol design UI and the protocol data model. It handles four categories of responsibility: protocol file I/O (load and save), process management (add and insert), order management (add, update, move, and delete), and selection state management (process and order selection along with grid service synchronization). It propagates UI refresh, error, and success messages through Qt signals, and synchronizes the user's grid selections bidirectionally with each order's target field via the `GridSelectionService`.
